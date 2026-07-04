"""
hoopwar.py — HoopWAR: one wins-above-replacement number per player.

DISPLAY-ONLY by design (founder decision 2026-07-01): HoopWAR is surfaced on the
player profile and the Impact Lab but is NOT folded into the OVERALL rating — its
core input (box-prior RAPM) already overlaps the rating's leaves, so folding it
in would double-count and disturb the SD=10 re-standardization contract.

Every link in the chain is an existing, tested engine — this module only chains
them (baseball-WAR style):

  impact rate   box-prior RAPM (helpers/rapm.py): ORAPM / DRAPM, points added per
                100 possessions on each end vs a league-AVERAGE player, with
                teammates and opponents held constant.
  replacement   a replacement-level player sits BELOW average (the kid off the
                bench who'd absorb the minutes). REPLACEMENT_PTS100 = −3.0 pts/100
                two-way; WAR pays (impact − replacement), so an exactly-average
                player still earns positive WAR over floor time — the defining
                property of the baseball stat.
  volume        the player's actual on-floor possessions (off + def) from the
                same RAPM possession walk. Impact is a rate; WAR pays it out
                over the floor time actually played.
  pts → wins    Pythagorean sensitivity: with exponent k and league per-team
                points-per-game P, one point of season-total margin ≈ k/(4·P)
                wins. k = league_analytics.PYTHAG_EXP (14, Basketball-Reference
                standard); P from finished Current-season scores. NBA sanity
                check: k=14, P=112 → ≈32 points per win, the classic number.
                At HS scale (P≈50) a win costs ≈14 points — HoopWAR of 1.0 means
                "this player's floor time added about a win over replacement."

  net points vs average = (ORAPM·off_poss + DRAPM·def_poss) / 100
  replacement debit     = REPLACEMENT_PTS100 · avg(off_poss, def_poss) / 100
  HoopWAR               = (net − debit) · k / (4·P)

Season WPA (helpers/wpa.py) is the sibling "realized wins" lens shown alongside —
deliberately NOT blended in: WPA already re-counts the same scoring impact through
the win-probability path, and it is vs-average not vs-replacement.

Pure data layer (mirrors helpers/stats.py): no streamlit. Callers that already
hold a cached compute_rapm() result pass it via `rapm=` so the ridge isn't solved
twice.
"""
from __future__ import annotations

from database.db import query
from helpers.league_analytics import PYTHAG_EXP

# Replacement level, points per 100 possessions below a league-average player.
# HS bench dropoff is steeper than pro, but the RAPM pool only contains rostered
# rotation players — −3.0/100 is the conservative, documented anchor (tunable).
REPLACEMENT_PTS100 = -3.0


def league_ppg(gender=None, season="Current"):
    """Average points per TEAM per game over finished games of `season` (both
    scores present). None when no finished games exist. `season` defaults to the
    active season; an archive view passes its label so HoopWAR's points-per-win
    scale isn't computed off an empty current season."""
    sql = ("SELECT AVG((g.home_score + g.away_score) / 2.0) p FROM games g "
           "JOIN teams t ON t.id = g.team1_id "
           "WHERE g.season=? AND g.home_score IS NOT NULL "
           "AND g.away_score IS NOT NULL")
    rows = query(sql + " AND t.gender=?", (season, gender)) if gender \
        else query(sql, (season,))
    p = rows[0]["p"] if rows else None
    return float(p) if p else None


def wins_per_point(ppg, exp=PYTHAG_EXP):
    """Wins one point of season-total scoring margin is worth: k / (4·P).
    Derivative of the Pythagorean win curve at an even game — independent of
    schedule length."""
    if not ppg:
        return None
    return exp / (4.0 * ppg)


def war_table(gender=None, rapm=None, game_ids=None, season="Current"):
    """HoopWAR for every player the RAPM pool can rate.

    `rapm` — pass a cached compute_rapm() result to skip re-solving the ridge
    (the UI path); default None solves box-prior RAPM over the gender's tracked
    games. Returns {player_id: {"WAR","pts_added","rapm","off_poss","def_poss",
    "name","team"}} plus a "_meta" key {"ppg","wins_per_pt","replacement","exp"};
    {} when RAPM can't solve or no finished scores exist. `season` scopes the
    points-per-win league baseline (so an archive still computes when the current
    season is empty).
    """
    if rapm is None:
        import helpers.rapm as RP
        if game_ids is None:
            import helpers.playtypes as PT
            game_ids = PT._tracked_game_ids(gender)
        if not game_ids:
            return {}
        try:
            prior = RP.box_prior_from_ratings(gender=gender)
            rapm = RP.compute_rapm(game_ids=game_ids, prior=prior)
        except Exception:
            return {}
    if not rapm:
        return {}

    ppg = league_ppg(gender, season)
    wpp = wins_per_point(ppg)
    if not wpp:
        return {}

    out = {"_meta": {"ppg": round(ppg, 1), "wins_per_pt": round(wpp, 4),
                     "pts_per_win": round(1.0 / wpp, 1),
                     "replacement": REPLACEMENT_PTS100, "exp": PYTHAG_EXP}}
    for pid, r in rapm.items():
        off_p, def_p = r.get("off_poss", 0), r.get("def_poss", 0)
        if not (off_p or def_p):
            continue
        net_vs_avg = (r["ORAPM"] * off_p + r["DRAPM"] * def_p) / 100.0
        repl_debit = REPLACEMENT_PTS100 * ((off_p + def_p) / 2.0) / 100.0
        pts_added = net_vs_avg - repl_debit          # debit is negative → adds
        out[pid] = {
            "WAR": round(pts_added * wpp, 2),
            "pts_added": round(pts_added, 1),
            "rapm": r.get("RAPM"),
            "off_poss": off_p, "def_poss": def_p,
            "name": r.get("name", str(pid)), "team": r.get("team", ""),
        }
    return out if len(out) > 1 else {}
