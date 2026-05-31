"""
wpa.py — Win Probability Added: scoring + possession-aware (value over expected).

Built on the win-probability engine. Two credit models:

  mode="scoring"     (default, conserving)
      Every MADE basket's WPA = the jump in the scoring team's win probability.
      Assisted FGs split 70/30 with the passer. This telescopes to the game's
      actual win-probability swing — the classic win-probability chart credit.

  mode="possession"  (advanced, value-over-expected — uses ALL the data)
      Every possession (shot OR turnover, the app's locked rule) is scored
      against its EXPECTED value. Expected points = league points-per-possession
      (EP). For each possession:
        offense WPA = WP(margin + actual_pts) − WP(margin + EP)
        defense WPA = −offense WPA
      Offense WPA is credited to the player who used the possession (scorer, or
      the turnover committer — so turnovers correctly hurt; assisted makes split
      with the passer). Defense WPA is credited to the player who DECIDED the
      possession: the stealer on a steal, the defensive rebounder on a forced
      miss (split with the blocker on a block), or the on-ball defender on a made
      basket. This is the win-probability translation of "points over expected"
      — it finally values steals, stops and blocks, not just buckets. It is a
      value-vs-baseline measure, NOT a conserving decomposition (both ends earn
      credit relative to the average possession).

Leverage Index (LI) = how much a basket would swing WP at that moment,
normalized to a per-game mean of 1.0; "clutch" sums a player's WPA in
high-leverage possessions (LI ≥ CLUTCH_LI). Free-throw points are excluded from
the possession model (FTs aren't possessions under the locked rule), consistent
with [[rapm]].

Pure data layer: database.db + helpers.win_probability + helpers.stats. No
streamlit, no scipy.
"""
from __future__ import annotations

from collections import defaultdict

from database.db import query
import helpers.win_probability as WP
import helpers.stats as S


CLUTCH_LI = 1.5         # leverage threshold for a moment to count as "clutch"
ASSIST_SHARE = 0.30     # share of a made FG's WPA credited to the passer
BLOCK_SHARE = 0.50      # share of a forced-miss stop credited to the blocker


def _clock_secs(t):
    try:
        m, s = (str(t).split(":") + ["0"])[:2]
        return int(m) * 60 + int(s)
    except Exception:
        return 0


def _q_len(q):
    return 480 if q <= 4 else 240


def _q_base(q):
    return 480 * (q - 1) if q <= 4 else 480 * 4 + 240 * (q - 5)


def _elapsed(q, t):
    return _q_base(q) + (_q_len(q) - _clock_secs(t))


def _safe(num, den):
    return num / den if den else 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  LEAGUE EXPECTED POINTS PER POSSESSION
# ══════════════════════════════════════════════════════════════════════════════

def league_ep(game_ids=None, events=None):
    """Average points per possession (shot/turnover) across the sample — the EP
    baseline the possession model scores each possession against."""
    if events is None:
        events = S.fetch_events(game_ids)
    pts = poss = 0
    for e in events:
        if e["event_type"] == "shot":
            poss += 1
            if e["shot_result"] == "make":
                pts += 3 if e["shot_type"] == 3 else 2
        elif e["event_type"] == "turnover":
            poss += 1
    return _safe(pts, poss)


# ══════════════════════════════════════════════════════════════════════════════
#  SINGLE-GAME WPA
# ══════════════════════════════════════════════════════════════════════════════

def game_wpa(game_id, mode="scoring", sd_full=WP.SD_FULL, ep=None):
    """
    Per-player WPA + clutch WPA + a win-probability timeline for one game.

    `mode` = "scoring" (made-basket WP jumps) or "possession" (value-over-
    expected over every shot/turnover possession; see module docstring).

    Returns {"players": {pid: {"wpa","clutch_wpa","off_wpa","def_wpa","plays",
    "name","team"}}, "timeline": [(elapsed, margin_home, wp_home)], "t1","t2",
    "t1name","t2name","end","mode"} or None if the game has no usable events.
    """
    g = query("""SELECT g.team1_id t1, g.team2_id t2, t1.name n1, t2.name n2
                 FROM games g JOIN teams t1 ON t1.id=g.team1_id
                 JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""", (game_id,))
    if not g:
        return None
    g = g[0]
    t1, t2 = g["t1"], g["t2"]

    events = S.fetch_events([game_id])
    if not events:
        return None
    events = sorted(events, key=lambda e: _elapsed(e["quarter"], e["time"]))
    end = max((_elapsed(e["quarter"], e["time"]) for e in events), default=1) or 1

    # roster names for everyone who appears
    names = {r["id"]: {"name": r["name"], "team": r["tn"]} for r in query(
        "SELECT p.id, p.name, t.name tn FROM players p JOIN teams t ON t.id=p.team_id")}

    # ── win-probability timeline (made FG/FT, home perspective) — for the chart ──
    timeline = []
    h = a = 0
    for e in events:
        if e["event_type"] in ("shot", "free_throw") and e["shot_result"] == "make":
            pts = e["shot_type"] if e["event_type"] == "shot" else 1
            if e["shooter_team_id"] == t1:
                h += pts
            elif e["shooter_team_id"] == t2:
                a += pts
            t = _elapsed(e["quarter"], e["time"])
            wp = WP.win_prob(h - a, max(end - t, 0), end, 0.0, sd_full)
            timeline.append((t, h - a, wp))

    players = defaultdict(lambda: {"wpa": 0.0, "clutch_wpa": 0.0,
                                   "off_wpa": 0.0, "def_wpa": 0.0, "plays": 0})

    def li_at(margin, secs_left):
        """Leverage = WP swing of a 2-pt basket here (un-normalized)."""
        return abs(WP.win_prob(margin + 2, secs_left, end, 0.0, sd_full)
                   - WP.win_prob(margin - 2, secs_left, end, 0.0, sd_full))

    if mode == "possession":
        if ep is None:
            ep = league_ep(events=events)
        h = a = 0
        contribs = []          # (pid, wpa, li, side)
        li_list = []
        for e in events:
            et = e["event_type"]
            if et not in ("shot", "turnover"):
                if et == "free_throw" and e["shot_result"] == "make":
                    if e["shooter_team_id"] == t1:
                        h += 1
                    elif e["shooter_team_id"] == t2:
                        a += 1
                continue
            off_team = e["shooter_team_id"]
            if off_team is None:
                continue
            t = _elapsed(e["quarter"], e["time"])
            secs_left = max(end - t, 0)
            mo = (h - a) if off_team == t1 else (a - h)   # offense's margin
            pts = (3 if e["shot_type"] == 3 else 2) if (
                et == "shot" and e["shot_result"] == "make") else 0

            wp_actual = WP.win_prob(mo + pts, secs_left, end, 0.0, sd_full)
            wp_expect = WP.win_prob(mo + ep, secs_left, end, 0.0, sd_full)
            off_wpa = wp_actual - wp_expect
            def_wpa = -off_wpa
            li = li_at(mo, secs_left)
            li_list.append(li)

            # offense credit
            user = e["primary_player_id"]
            passer = e["pass_from_id"] if (et == "shot" and e["shot_result"] == "make") else None
            if user is not None:
                if passer is not None:
                    contribs.append((user, off_wpa * (1 - ASSIST_SHARE), li, "off"))
                    contribs.append((passer, off_wpa * ASSIST_SHARE, li, "off"))
                else:
                    contribs.append((user, off_wpa, li, "off"))

            # defense credit
            if et == "turnover":
                if e["stolen_by_id"] is not None:
                    contribs.append((e["stolen_by_id"], def_wpa, li, "def"))
            elif e["shot_result"] == "make":
                if e["guarded_by_id"] is not None:
                    contribs.append((e["guarded_by_id"], def_wpa, li, "def"))
            else:  # missed shot
                reb = e["rebound_by_id"]
                if reb is not None and e["rebounder_team_id"] is not None \
                        and e["rebounder_team_id"] != off_team:
                    blocker = e["blocked_by_id"]
                    if blocker is not None:
                        contribs.append((blocker, def_wpa * BLOCK_SHARE, li, "def"))
                        contribs.append((reb, def_wpa * (1 - BLOCK_SHARE), li, "def"))
                    else:
                        contribs.append((reb, def_wpa, li, "def"))

            if off_team == t1:
                h += pts
            else:
                a += pts

        li_mean = (sum(li_list) / len(li_list)) if li_list else 1.0
        li_mean = li_mean or 1.0
        for pid, val, li, side in contribs:
            rec = players[pid]
            rec["wpa"] += val
            rec[side + "_wpa"] += val
            rec["plays"] += 1
            if li / li_mean >= CLUTCH_LI:
                rec["clutch_wpa"] += val

    else:  # ── scoring mode (conserving, made baskets only) ──────────────────
        h = a = 0
        rows = []
        for e in events:
            if e["event_type"] not in ("shot", "free_throw") or e["shot_result"] != "make":
                continue
            pts = e["shot_type"] if e["event_type"] == "shot" else 1
            t = _elapsed(e["quarter"], e["time"])
            secs_left = max(end - t, 0)
            mb = h - a
            if e["shooter_team_id"] == t1:
                h += pts
            elif e["shooter_team_id"] == t2:
                a += pts
            ma = h - a
            d_home = (WP.win_prob(ma, secs_left, end, 0.0, sd_full)
                      - WP.win_prob(mb, secs_left, end, 0.0, sd_full))
            wpa_team = d_home if e["shooter_team_id"] == t1 else -d_home
            rows.append((e["primary_player_id"],
                         e["pass_from_id"] if e["event_type"] == "shot" else None,
                         wpa_team, li_at(mb, secs_left)))
        li_mean = (sum(r[3] for r in rows) / len(rows)) if rows else 1.0
        li_mean = li_mean or 1.0
        for pid, passer, wpa_team, li in rows:
            clutch = li / li_mean >= CLUTCH_LI
            if passer is not None:
                for who, share in ((pid, 1 - ASSIST_SHARE), (passer, ASSIST_SHARE)):
                    rec = players[who]
                    rec["wpa"] += wpa_team * share
                    rec["off_wpa"] += wpa_team * share
                    rec["plays"] += 1
                    if clutch:
                        rec["clutch_wpa"] += wpa_team * share
            elif pid is not None:
                rec = players[pid]
                rec["wpa"] += wpa_team
                rec["off_wpa"] += wpa_team
                rec["plays"] += 1
                if clutch:
                    rec["clutch_wpa"] += wpa_team

    out_players = {}
    for pid, rec in players.items():
        out_players[pid] = {
            "wpa": round(rec["wpa"], 3),
            "clutch_wpa": round(rec["clutch_wpa"], 3),
            "off_wpa": round(rec["off_wpa"], 3),
            "def_wpa": round(rec["def_wpa"], 3),
            "plays": rec["plays"],
            "name": names.get(pid, {}).get("name", str(pid)),
            "team": names.get(pid, {}).get("team", ""),
        }
    return {"players": out_players, "timeline": timeline,
            "t1": t1, "t2": t2, "t1name": g["n1"], "t2name": g["n2"],
            "end": end, "mode": mode}


# ══════════════════════════════════════════════════════════════════════════════
#  SEASON WPA  (aggregate across tracked games)
# ══════════════════════════════════════════════════════════════════════════════

def season_wpa(gender=None, mode="scoring"):
    """
    Aggregate WPA across every tracked game for a gender, in the chosen mode.

    Returns {player_id: {"wpa","clutch_wpa","off_wpa","def_wpa","plays","games",
    "wpa_per_game","name","team"}}. In possession mode off_wpa/def_wpa split a
    player's value into the offense and defense it created vs expectation.
    """
    tg = query(
        """SELECT g.id FROM games g JOIN teams t ON t.id=g.team1_id
           WHERE g.tracked=1 AND t.gender=?""", (gender,)) if gender else query(
        "SELECT id FROM games WHERE tracked=1")
    ep = league_ep() if mode == "possession" else None

    agg = defaultdict(lambda: {"wpa": 0.0, "clutch_wpa": 0.0, "off_wpa": 0.0,
                               "def_wpa": 0.0, "plays": 0, "games": 0,
                               "name": "", "team": ""})
    for row in tg:
        res = game_wpa(row["id"], mode=mode, ep=ep)
        if not res:
            continue
        for pid, r in res["players"].items():
            a = agg[pid]
            for k in ("wpa", "clutch_wpa", "off_wpa", "def_wpa", "plays"):
                a[k] += r[k]
            a["games"] += 1
            a["name"], a["team"] = r["name"], r["team"]
    out = {}
    for pid, a in agg.items():
        out[pid] = {
            "wpa": round(a["wpa"], 3), "clutch_wpa": round(a["clutch_wpa"], 3),
            "off_wpa": round(a["off_wpa"], 3), "def_wpa": round(a["def_wpa"], 3),
            "plays": a["plays"], "games": a["games"],
            "wpa_per_game": round(a["wpa"] / a["games"], 3) if a["games"] else 0.0,
            "name": a["name"], "team": a["team"],
        }
    return out
