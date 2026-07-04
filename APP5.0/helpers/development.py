"""
development.py — cross-season player development (Tier 3, ML_LAYER_ROADMAP).

Builds on the identity link (helpers/identity.py): for a PERSON (across however many
seasons their rows are linked), produce the season-by-season stat lines, the
year-over-year progression/regression, and a rough next-season projection.

Honest about data maturity: with one tracked season this shows a single line and the
deltas / projection say "unlocks after a 2nd linked season." It lights up
automatically as rollovers link more seasons — no code change needed. The projection
blends the player's own YoY trend with a league CLASS-CURVE (typical jump by class,
from every multi-season player), which is the "more year-over-year data" the curve
needs; until that population exists it falls back to the own-trend (regressed, wide
band) and is always labeled a lean, never a promise.

Pure data layer (reuses stats per-season boxes + identity + seasons). No streamlit.
"""
from __future__ import annotations

from database.db import query
import helpers.stats as S
import helpers.identity as IDN
import helpers.seasons as SZ

# per-game counting stats tracked across seasons (label, box key). TPG/FPG are
# "lower is better" — _trend inverts them.
_PERGAME = [("PPG", "PTS"), ("RPG", "TRB"), ("APG", "AST"),
            ("SPG", "STL"), ("BPG", "BLK"), ("TPG", "TOV"), ("FPG", "PF")]
_INVERTED = {"TPG", "FPG"}        # more = worse, so a positive YoY delta is a ▼
_SHOOT = ("FG%", "3P%", "FT%", "eFG", "TS%")
MIN_GP = 3                # min games in a season before its line drives a delta
TREND_EPS = {"PPG": 1.5, "RPG": 1.0, "APG": 0.8, "SPG": 0.4, "BPG": 0.4,
             "TPG": 0.6, "FPG": 0.6, "FG%": 3.0, "3P%": 4.0, "FT%": 4.0,
             "eFG": 3.0, "TS%": 3.0}
_CLASS = {0: "Sr", 1: "Jr", 2: "So", 3: "Fr"}


def _pct(m, a):
    return round(100.0 * m / a, 1) if a else None


def identity_of(player_id):
    """The stable person key for a player row (COALESCE(identity_id, id))."""
    r = query("SELECT COALESCE(identity_id, id) AS k FROM players WHERE id=?",
              (int(player_id),))
    return r[0]["k"] if r else int(player_id)


def class_of(grad_year, season_label):
    """Class (Fr/So/Jr/Sr) of a player in a season, from grad_year vs that season's
    graduating year. None if unknown."""
    end = SZ.graduating_year(SZ.active_label() if SZ.is_current(season_label)
                             else season_label)
    if grad_year is None or end is None:
        return None
    return _CLASS.get(grad_year - end)


def _season_gids(season, team_id):
    return [r["id"] for r in query(
        "SELECT id FROM games WHERE tracked=1 AND season=? AND (team1_id=? OR team2_id=?)",
        (season, team_id, team_id))]


def season_lines(identity_key):
    """Per-season stat line for one person, OLDEST season first. Each line:
    {season, label, team, player_id, grad_year, klass, gp, PPG..FPG, FG%,3P%,FT%,
    eFG,TS%, PTS}. Rates are None for a season with no tracked games."""
    rows = IDN.identity_history(identity_key)
    teams = {t["id"]: t["name"] for t in query("SELECT id, name FROM teams")}
    grad = {r["id"]: r.get("grad_year") for r in query(
        "SELECT id, grad_year FROM players")}
    out = []
    for r in rows:
        season, pid, tid = r["season"], r["id"], r["team_id"]
        gids = _season_gids(season, tid)
        gp = S.games_played(gids).get(pid, 0) if gids else 0
        line = {
            "season": season,
            "label": (SZ.active_label() if SZ.is_current(season) else season),
            "team": teams.get(tid, "?"), "player_id": pid,
            "grad_year": grad.get(pid),
            "klass": class_of(grad.get(pid), season), "gp": gp,
        }
        if gids and gp:
            b = S.player_box(pid, gids)
            for lab, k in _PERGAME:
                line[lab] = round(b.get(k, 0) / gp, 1)
            line["FG%"] = _pct(b["FGM"], b["FGA"])
            line["3P%"] = _pct(b["3PM"], b["3PA"])
            line["FT%"] = _pct(b["FTM"], b["FTA"])
            line["eFG"] = _pct(b["FGM"] + 0.5 * b["3PM"], b["FGA"])
            line["TS%"] = _pct(b["PTS"], 2 * (b["FGA"] + 0.44 * b["FTA"])) \
                if (b["FGA"] + b["FTA"]) else None
            line["PTS"] = b["PTS"]
        else:
            for lab, _ in _PERGAME:
                line[lab] = None
            for k in _SHOOT:
                line[k] = None
            line["PTS"] = 0
        out.append(line)
    return out


def _trend(lab, delta):
    """▲ / ▼ / — for a YoY delta, gated by a per-stat meaningfulness epsilon. TOV
    and fouls are inverted (fewer = improvement)."""
    eps = TREND_EPS.get(lab, 0.0)
    if delta is None or abs(delta) < eps:
        return "—"
    up = delta > 0
    if lab in _INVERTED:
        up = not up
    return "▲" if up else "▼"


def progression(identity_key):
    """Season lines + the YoY change between the two most recent RATED seasons
    (gp>=MIN_GP). Returns {lines, rated_seasons, prev, cur, deltas:{lab:{delta,trend}},
    headline}. deltas is None until two rated seasons exist."""
    lines = season_lines(identity_key)
    rated = [l for l in lines if l["gp"] >= MIN_GP]
    out = {"lines": lines, "rated_seasons": len(rated),
           "prev": None, "cur": None, "deltas": None, "headline": None}
    if len(rated) < 2:
        return out
    prev, cur = rated[-2], rated[-1]
    deltas = {}
    for lab in [l for l, _ in _PERGAME] + list(_SHOOT):
        a, b = prev.get(lab), cur.get(lab)
        if a is not None and b is not None:
            d = round(b - a, 1)
            deltas[lab] = {"delta": d, "trend": _trend(lab, d)}
    out.update(prev=prev, cur=cur, deltas=deltas)
    if "PPG" in deltas:
        d = deltas["PPG"]["delta"]
        out["headline"] = (f"PPG {d:+.1f} {deltas['PPG']['trend']} "
                           f"({prev['PPG']:.1f} → {cur['PPG']:.1f})")
    return out


def class_curve(gender=None):
    """League CLASS-CURVE: mean YoY delta per stat by the FROM-class (So→, Jr→, …),
    over every person with two consecutive rated seasons. The population age-curve
    the projection leans on. Empty until enough multi-season players exist.

    Returns {from_class: {stat: mean_delta, "_n": pairs}}."""
    keys = [r["k"] for r in query(
        "SELECT DISTINCT COALESCE(identity_id, id) AS k FROM players")]
    acc = {}
    for k in keys:
        lines = [l for l in season_lines(k) if l["gp"] >= MIN_GP]
        for prev, cur in zip(lines, lines[1:]):
            fc = prev.get("klass")
            if not fc:
                continue
            bucket = acc.setdefault(fc, {"_n": 0})
            bucket["_n"] += 1
            for lab in [l for l, _ in _PERGAME] + list(_SHOOT):
                a, b = prev.get(lab), cur.get(lab)
                if a is not None and b is not None:
                    bucket.setdefault(lab, []).append(b - a)
    out = {}
    for fc, b in acc.items():
        row = {"_n": b["_n"]}
        for lab, vals in b.items():
            if lab != "_n" and vals:
                row[lab] = round(sum(vals) / len(vals), 2)
        out[fc] = row
    return out


def project_next(identity_key, gender=None, curve=None):
    """Rough next-season projection. Returns {"ok": False, "reason": ...} until the
    person has two rated seasons; else {"ok": True, "proj": {lab: value}, "basis",
    "from_class", "to_class", "note"}.

    Method: start from the last rated season; nudge by the player's own YoY delta
    (regressed 50% — a single delta is noisy) blended with the league class-curve
    delta for their class transition when that population exists. Always a lean."""
    prog = progression(identity_key)
    rated = [l for l in prog["lines"] if l["gp"] >= MIN_GP]
    if len(rated) < 2:
        return {"ok": False,
                "reason": "Year-over-year projection unlocks after a 2nd linked "
                          "season (roll over, link the player, track games)."}
    cur = rated[-1]
    own = {lab: d["delta"] for lab, d in (prog["deltas"] or {}).items()}
    if curve is None:
        curve = class_curve(gender)
    fc = cur.get("klass")
    cc = curve.get(fc, {}) if fc else {}
    proj = {}
    for lab, _ in _PERGAME:
        base = cur.get(lab)
        if base is None:
            continue
        od = own.get(lab, 0.0) * 0.5
        cd = cc.get(lab)
        step = (od + cd) / 2.0 if cd is not None else od
        proj[lab] = round(max(0.0, base + step), 1)
    return {"ok": True, "proj": proj,
            "basis": "own-trend + class-curve" if cc else "own-trend",
            "from_class": fc, "to_class": _CLASS.get(
                {"Fr": 2, "So": 1, "Jr": 0}.get(fc, -1)) if fc else None,
            "note": "Rough — built on limited year-over-year change; treat as a lean."}


def project_rest_of_season(player_id, boxes=None, form_weight=0.25,
                           shrink_k=3, min_gp=3):
    """Rest-of-THIS-season projection for a current-season player — no linked
    past season required (the next-season projection stays gated on two).

    Method (real numbers, no invented ceiling): per-game rates so far, tilted
    toward last-5 form (``form_weight``); under 6 games the rate is also shrunk
    toward the league per-game mean (weight gp/(gp+shrink_k)) so a 3-game line
    doesn't extrapolate raw. Remaining games = the team's scoreless games this
    season. Returns {"ok": False, "reason"} when the player is archived, has
    fewer than ``min_gp`` games, or the schedule has no games left; else
    {"ok": True, "gp", "remaining", "per_game": {lab: rate},
     "season_end": {lab: projected season total}, "note"}."""
    p = query("SELECT team_id, archived FROM players WHERE id=?", (player_id,))
    if not p:
        return {"ok": False, "reason": "Unknown player."}
    if p[0]["archived"]:
        return {"ok": False, "reason": "Season over — this is an archived "
                                       "season's line."}
    if boxes is None:
        boxes = S.player_game_boxes()
    pb = boxes.get(player_id, {})
    gp = len(pb)
    if gp < min_gp:
        return {"ok": False,
                "reason": f"Rest-of-season projection needs {min_gp}+ tracked "
                          f"games ({gp} so far)."}
    remaining = query(
        """SELECT COUNT(*) n FROM games
           WHERE (team1_id=? OR team2_id=?) AND season='Current'
             AND (home_score IS NULL OR away_score IS NULL)""",
        (p[0]["team_id"], p[0]["team_id"]))[0]["n"]
    if not remaining:
        return {"ok": False, "reason": "No games left on the schedule — the "
                                       "season line is final."}
    # per-game rates: season + last-5 form tilt (game_id order = insertion
    # order, a fine recency proxy)
    ordered = [pb[g] for g in sorted(pb)]
    per_game, season_end = {}, {}
    lg_mean = {}
    if gp < 6:            # small book → also shrink toward the league mean
        for lab, key in _PERGAME:
            vals = [sum(b.get(key, 0) for b in d.values()) / len(d)
                    for d in boxes.values() if d]
            lg_mean[lab] = sum(vals) / len(vals) if vals else 0.0
    w_form = form_weight if gp >= 6 else 0.0
    w_self = gp / (gp + shrink_k) if gp < 6 else 1.0
    for lab, key in _PERGAME:
        tot = sum(b.get(key, 0) for b in ordered)
        season = tot / gp
        last5 = sum(b.get(key, 0) for b in ordered[-5:]) / min(5, gp)
        rate = (1 - w_form) * season + w_form * last5
        rate = w_self * rate + (1 - w_self) * lg_mean.get(lab, rate)
        per_game[lab] = round(rate, 1)
        season_end[lab] = round(tot + rate * remaining)
    return {"ok": True, "gp": gp, "remaining": remaining,
            "per_game": per_game, "season_end": season_end,
            "note": ("Measured rates carried over the remaining schedule"
                     + (" (last-5 form tilted)" if w_form else
                        " (small sample — shrunk toward league average)")
                     + "; scoreless scheduled games count as remaining.")}


def player_development(player_id, gender=None, curve=None):
    """One bundle for the player card: {identity_key, progression, projection,
    rest_of_season}. Graceful — single-season players get a one-line history and
    a 'needs a 2nd season' projection, but rest_of_season works from the FIRST
    season (3+ games). `curve` (a precomputed class_curve) lets the caller cache
    the expensive league pass; only consulted once a player has two rated seasons."""
    key = identity_of(player_id)
    prog = progression(key)
    proj = project_next(key, gender=gender, curve=curve)
    try:
        ros = project_rest_of_season(player_id)
    except Exception:
        ros = {"ok": False, "reason": ""}
    return {"identity_key": key, "progression": prog, "projection": proj,
            "rest_of_season": ros}
