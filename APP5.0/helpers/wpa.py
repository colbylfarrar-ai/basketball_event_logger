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


# Game-clock helpers — canonical versions live in helpers.stats.
_clock_secs = S.clock_secs
_q_len = S.q_len
_q_base = S.q_base
_elapsed = S.elapsed


_safe = S._safe   # shared definition lives in helpers.stats


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

def game_wpa(game_id, mode="scoring", sd_full=WP.SD_FULL, ep=None,
             events=None, names=None, ginfo=None, pregame_edge=0.0):
    """
    Per-player WPA + clutch WPA + a win-probability timeline for one game.

    `mode` = "scoring" (made-basket WP jumps) or "possession" (value-over-
    expected over every shot/turnover possession; see module docstring).

    `pregame_edge` = the pre-game expected margin (home − away = team1 − team2, in
    points) so the win-probability model knows the matchup wasn't even. 0.0 treats
    the teams as evenly matched (the historical default; leaves every existing
    number unchanged). season_wpa fills this from the opponent-adjusted ratings so
    a comeback or a defensive stop earned as the underdog is weighted UP and
    padding a blowout is weighted DOWN — the opponent-strength dimension of value.

    `events` / `names` / `ginfo` are optional pre-fetched inputs so a season-wide
    caller can fetch them ONCE and avoid re-querying per game (see season_wpa):
      • events — this game's event rows (else fetched here),
      • names  — {pid: {"name","team"}} roster map, game-independent (else fetched),
      • ginfo  — {"t1","t2","n1","n2"} game/team info (else fetched).

    Returns {"players": {pid: {"wpa","clutch_wpa","off_wpa","def_wpa","plays",
    "name","team"}}, "timeline": [(elapsed, margin_home, wp_home)], "t1","t2",
    "t1name","t2name","end","mode"} or None if the game has no usable events.
    """
    if ginfo is None:
        g = query("""SELECT g.team1_id t1, g.team2_id t2, t1.name n1, t2.name n2
                     FROM games g JOIN teams t1 ON t1.id=g.team1_id
                     JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""", (game_id,))
        if not g:
            return None
        g = g[0]
    else:
        g = ginfo
    t1, t2 = g["t1"], g["t2"]

    if events is None:
        events = S.fetch_events([game_id])
    if not events:
        return None
    events = sorted(events, key=lambda e: _elapsed(e["quarter"], e["time"]))
    end = max((_elapsed(e["quarter"], e["time"]) for e in events), default=1) or 1

    # roster names for everyone who appears (game-independent — pass in to reuse)
    if names is None:
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
            wp = WP.win_prob(h - a, max(end - t, 0), end, pregame_edge, sd_full)
            timeline.append((t, h - a, wp))

    players = defaultdict(lambda: {"wpa": 0.0, "clutch_wpa": 0.0,
                                   "off_wpa": 0.0, "def_wpa": 0.0, "plays": 0})

    def li_at(margin, secs_left, edge=0.0):
        """Leverage = WP swing of a 2-pt basket here (un-normalized). `edge` is
        the pre-game spread in the SAME perspective as `margin` — home for the
        scoring/timeline path, the offense's perspective for a possession."""
        return abs(WP.win_prob(margin + 2, secs_left, end, edge, sd_full)
                   - WP.win_prob(margin - 2, secs_left, end, edge, sd_full))

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
            # pre-game spread from the OFFENSE's perspective — flip it when the
            # offense is the away team, since `mo` is then an away-margin.
            off_edge = pregame_edge if off_team == t1 else -pregame_edge
            pts = (3 if e["shot_type"] == 3 else 2) if (
                et == "shot" and e["shot_result"] == "make") else 0

            wp_actual = WP.win_prob(mo + pts, secs_left, end, off_edge, sd_full)
            wp_expect = WP.win_prob(mo + ep, secs_left, end, off_edge, sd_full)
            off_wpa = wp_actual - wp_expect
            def_wpa = -off_wpa
            li = li_at(mo, secs_left, off_edge)
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
            d_home = (WP.win_prob(ma, secs_left, end, pregame_edge, sd_full)
                      - WP.win_prob(mb, secs_left, end, pregame_edge, sd_full))
            wpa_team = d_home if e["shooter_team_id"] == t1 else -d_home
            rows.append((e["primary_player_id"],
                         e["pass_from_id"] if e["event_type"] == "shot" else None,
                         wpa_team, li_at(mb, secs_left, pregame_edge)))
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

def season_wpa(gender=None, mode="scoring", opp_adjust=True, season="Current"):
    """
    Aggregate WPA across every tracked game for a gender, in the chosen mode.

    `opp_adjust` (default True) feeds each game's pre-game spread — from the
    opponent-adjusted score ratings (helpers.team_ratings) — into the win-
    probability model, so value created against a stronger opponent (as the
    underdog) is weighted up and padding a blowout is weighted down. Set False for
    the legacy even-teams behaviour. Unrated matchups fall back to even teams.

    Returns {player_id: {"wpa","clutch_wpa","off_wpa","def_wpa","plays","games",
    "wpa_per_game","name","team"}}. In possession mode off_wpa/def_wpa split a
    player's value into the offense and defense it created vs expectation.
    """
    tg = query(
        """SELECT g.id FROM games g JOIN teams t ON t.id=g.team1_id
           WHERE g.tracked=1 AND g.season=? AND t.gender=?""", (season, gender)) if gender else query(
        "SELECT id FROM games WHERE tracked=1 AND season=?", (season,))
    ep = league_ep() if mode == "possession" else None
    game_ids = [row["id"] for row in tg]

    # Fetch the per-game inputs ONCE instead of inside game_wpa per game (was an
    # N+1: each call re-pulled events + the full roster + game info). Now ~4
    # queries total regardless of game count.
    ev_by_game = defaultdict(list)
    for e in S.fetch_events(game_ids):
        ev_by_game[e["game_id"]].append(e)
    names = {r["id"]: {"name": r["name"], "team": r["tn"]} for r in query(
        "SELECT p.id, p.name, t.name tn FROM players p JOIN teams t ON t.id=p.team_id")}
    ginfo = {}
    if game_ids:
        _ph = ",".join("?" * len(game_ids))
        ginfo = {r["id"]: {"t1": r["t1"], "t2": r["t2"], "n1": r["n1"], "n2": r["n2"]}
                 for r in query(
                     f"""SELECT g.id, g.team1_id t1, g.team2_id t2,
                                t1.name n1, t2.name n2
                         FROM games g JOIN teams t1 ON t1.id=g.team1_id
                         JOIN teams t2 ON t2.id=g.team2_id
                         WHERE g.id IN ({_ph})""", tuple(game_ids))}

    # Opponent-strength edge per game: the neutral-floor pre-game spread (team1 −
    # team2) from the opponent-adjusted score ratings, fed to the WP model so the
    # underdog's value is weighted up. Computed once; unrated matchups → edge 0.
    TR = scored = None
    if opp_adjust:
        import helpers.team_ratings as TR
        scored = TR.score_ratings(gender=gender)

    agg = defaultdict(lambda: {"wpa": 0.0, "clutch_wpa": 0.0, "off_wpa": 0.0,
                               "def_wpa": 0.0, "plays": 0, "games": 0,
                               "name": "", "team": ""})
    for row in tg:
        gid = row["id"]
        gi = ginfo.get(gid)
        edge = 0.0
        if scored and gi:
            edge = TR.predict_spread(scored, gi["t1"], gi["t2"]) or 0.0
        res = game_wpa(gid, mode=mode, ep=ep, events=ev_by_game.get(gid, []),
                       names=names, ginfo=gi, pregame_edge=edge)
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
