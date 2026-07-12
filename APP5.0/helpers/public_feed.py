"""
public_feed.py — allowlisted game state for the PUBLIC fan link (no login).

This is the ONLY code that shapes what an anonymous fan can see. The payload
is built by explicit construction — every field below is deliberately public;
nothing else from the row/event objects is ever copied in. Keep it that way:
when adding a field, ask "would I put this on a gym scoreboard?".

Public by design:  score, status, quarter/clock, quarter scores, team fouls,
                   per-player box lines keyed by JERSEY NUMBER, play-by-play
                   strings (numbers only), shot-chart dots, officials as
                   anonymized crew slots (R/U1/U2) with foul counts.
Never public:      player names, official names, play_type, defense,
                   turnover_type, foul_type, ratings of any kind, minutes,
                   possession counts.

Fans poll every few seconds, so `state_by_token` sits behind a small TTL
cache: N fans on one game cost ~1 DB read per TTL window.
"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import date as _date

from database.db import execute, query
import helpers.event_log as EL
import helpers.stats as ST
import helpers.win_probability as WP

CACHE_TTL = 3.0          # seconds; fan polling is decoupled from DB reads
_CACHE: dict[str, tuple[float, dict]] = {}

# crew-slot labels in assigning order; slot column 1-based, extras become U3…
_SLOT_LABELS = ("R", "U1", "U2", "U3", "U4")


def clear_cache() -> None:
    _CACHE.clear()
    _SB_CACHE.clear()
    _TEAM_CACHE.clear()


_SB_CACHE: dict[str, tuple[float, dict]] = {}


def scoreboard(date_str: str) -> dict | None:
    """Public landing payload: every public game LIVE right now (last ~day so a
    late tip survives the UTC date line) + one calendar date's slate. Same
    allowlist discipline as the game feed — team names, finals' scores, live
    public games' scores; a non-public in-progress game lists as a plain
    upcoming row (no score, no link, no hint it's being tracked). Returns None
    on a malformed date (router turns that into a 422)."""
    date_str = (date_str or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return None
    hit = _SB_CACHE.get(date_str)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    live_rows = query(
        "SELECT g.id, g.share_token, g.date, g.location, "
        "       t1.name AS hn, t2.name AS an, t1.gender AS gd "
        "FROM games g JOIN teams t1 ON t1.id=g.team1_id "
        "             JOIN teams t2 ON t2.id=g.team2_id "
        "WHERE g.is_public=1 AND g.tracked=0 AND g.share_token<>'' "
        "  AND g.date >= date('now','-1 day') "
        "  AND EXISTS (SELECT 1 FROM game_events e WHERE e.game_id=g.id) "
        "ORDER BY g.date DESC, g.id DESC LIMIT 50")
    live, live_ids = [], set()
    for r in live_rows:
        hp, ap = EL.score_from_events(r["id"]) or (0, 0)
        last = query("SELECT quarter, time FROM game_events WHERE game_id=? "
                     "ORDER BY id DESC LIMIT 1", (r["id"],))
        live_ids.add(r["id"])
        live.append({"home": r["hn"], "away": r["an"],
                     "gender": "Girls" if r["gd"] == "F" else "Boys",
                     "home_pts": hp, "away_pts": ap,
                     "quarter": last[0]["quarter"], "clock": last[0]["time"],
                     "date": r["date"], "url": f"/live/{r['share_token']}"})

    _slate_cols = (
        "SELECT g.id, g.date, g.tracked, g.home_score, g.away_score, g.is_public, "
        "       g.share_token, g.location, g.team1_id, g.team2_id, "
        "       t1.name AS hn, t2.name AS an, t1.gender AS gd, "
        "       t1.class AS hc, t2.class AS ac "
        "FROM games g JOIN teams t1 ON t1.id=g.team1_id "
        "             JOIN teams t2 ON t2.id=g.team2_id ")

    def _row(r, status):
        g = {"home": r["hn"], "away": r["an"],
             "home_id": r["team1_id"], "away_id": r["team2_id"],
             "gender": "Girls" if r["gd"] == "F" else "Boys",
             "classes": sorted({c for c in (r["hc"], r["ac"]) if c and c != "N/A"}),
             "status": status, "location": r["location"] or "", "date": r["date"]}
        if status == "final":
            g["home_score"], g["away_score"] = r["home_score"], r["away_score"]
        if r["is_public"] and r["share_token"]:
            g["url"] = f"/live/{r['share_token']}"
        return g

    rows = query(_slate_cols + "WHERE g.date=? ORDER BY t1.name, g.id LIMIT 300",
                 (date_str,))
    games = []
    for r in rows:
        final = bool(r["tracked"]) or (r["home_score"] is not None
                                       and r["away_score"] is not None)
        status = "live" if r["id"] in live_ids else ("final" if final else "upcoming")
        games.append(_row(r, status))

    # latest-finals rail: most recent finished games (any date), newest first
    recent = [_row(r, "final") for r in query(
        _slate_cols +
        "WHERE (g.tracked=1 OR (g.home_score IS NOT NULL AND g.away_score IS NOT NULL)) "
        "AND g.date >= date('now','-3 day') AND g.id NOT IN "
        "(SELECT id FROM games WHERE date=?) "
        "ORDER BY g.date DESC, g.id DESC LIMIT 12", (date_str,))]

    payload = {"date": date_str, "live": live, "games": games, "recent": recent}
    _SB_CACHE[date_str] = (now, payload)
    return payload


def state_by_token(token: str, viewer: str | None = None) -> dict | None:
    """Public payload for a share token, or None (unknown token OR a game the
    coach has not made public — identical outcome, no existence leak). Pass a
    stable `viewer` key (hashed ip+ua) to tally the coach-facing fan counter —
    counted once per viewer per day, never per poll."""
    token = (token or "").strip()
    if not token:
        return None
    hit = _CACHE.get(token)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL:
        if viewer:
            _count_view(hit[2], viewer)
        return hit[1]
    g = query(
        "SELECT g.id, g.date, g.location, g.tracked, "
        "       t1.name AS home_name, t2.name AS away_name, "
        "       g.team1_id, g.team2_id "
        "FROM games g JOIN teams t1 ON t1.id=g.team1_id "
        "             JOIN teams t2 ON t2.id=g.team2_id "
        "WHERE g.share_token=? AND g.is_public=1", (token,))
    if not g:
        return None
    payload = _build_state(dict(g[0]))
    _CACHE[token] = (now, payload, g[0]["id"])
    if viewer:
        _count_view(g[0]["id"], viewer)
    return payload


# ── fan counter (coach-facing telemetry; never in the public payload) ───────────
_SEEN_VIEWERS: set[tuple] = set()


def viewer_key(ip: str, ua: str) -> str:
    """Stable anonymous viewer id — hash only, raw ip/ua never stored."""
    return hashlib.sha1(f"{ip}|{ua}".encode()).hexdigest()[:16]


def _count_view(game_id: int, viewer: str) -> None:
    day = _date.today().isoformat()
    key = (game_id, day, viewer)
    if key in _SEEN_VIEWERS:
        return
    if len(_SEEN_VIEWERS) > 50000:      # bound memory; worst case = recount
        _SEEN_VIEWERS.clear()
    _SEEN_VIEWERS.add(key)
    try:
        execute("INSERT INTO fan_views (game_id, day, viewers) VALUES (?,?,1) "
                "ON CONFLICT(game_id, day) DO UPDATE SET viewers=viewers+1",
                (game_id, day))
    except Exception:
        pass                            # telemetry never breaks the feed


def fan_count(game_id: int) -> int:
    r = query("SELECT COALESCE(SUM(viewers),0) AS n FROM fan_views "
              "WHERE game_id=?", (game_id,))
    return int(r[0]["n"])


# ── public team profile ─────────────────────────────────────────────────────────
_TEAM_CACHE: dict[int, tuple[float, dict]] = {}


def team_profile(team_id: int) -> dict | None:
    """Public team page payload: identity, W-L record, season results +
    upcoming schedule (fan links where they exist). Team-level public-record
    facts only — no ratings, no players. Season = the team's most recent
    game's season, so a post-rollover archive still shows the played season."""
    hit = _TEAM_CACHE.get(team_id)
    now = time.monotonic()
    if hit and now - hit[0] < 10.0:
        return hit[1]
    t = query("SELECT id, name, class, gender FROM teams WHERE id=?", (team_id,))
    if not t:
        return None
    t = t[0]
    szn = query("SELECT season FROM games WHERE team1_id=? OR team2_id=? "
                "ORDER BY date DESC, id DESC LIMIT 1", (team_id, team_id))
    season = szn[0]["season"] if szn else None
    games, wins, losses = [], 0, 0
    if season:
        rows = query(
            "SELECT g.id, g.date, g.location, g.tracked, g.home_score, "
            "       g.away_score, g.is_public, g.share_token, g.team1_id, "
            "       t1.name AS hn, t2.name AS an "
            "FROM games g JOIN teams t1 ON t1.id=g.team1_id "
            "             JOIN teams t2 ON t2.id=g.team2_id "
            "WHERE (g.team1_id=? OR g.team2_id=?) AND g.season=? "
            "ORDER BY g.date DESC, g.id DESC LIMIT 60",
            (team_id, team_id, season))
        for r in rows:
            is_home = r["team1_id"] == team_id
            final = bool(r["tracked"]) or (r["home_score"] is not None
                                           and r["away_score"] is not None)
            us = r["home_score"] if is_home else r["away_score"]
            them = r["away_score"] if is_home else r["home_score"]
            g = {"date": r["date"], "opp": r["an"] if is_home else r["hn"],
                 "home_away": "vs" if is_home else "at",
                 "status": "final" if final else "upcoming",
                 "location": r["location"] or ""}
            if final and us is not None:
                g["us"], g["them"] = us, them
                g["won"] = us > them
                wins += 1 if us > them else 0
                losses += 1 if us < them else 0
            if r["is_public"] and r["share_token"]:
                g["url"] = f"/live/{r['share_token']}"
            games.append(g)
    payload = {"id": t["id"], "name": t["name"],
               "class": t["class"] if t["class"] != "N/A" else "",
               "gender": "Girls" if t["gender"] == "F" else "Boys",
               "season": season if season and season != "Current" else "",
               "wins": wins, "losses": losses,
               "games": games}
    _TEAM_CACHE[team_id] = (now, payload)
    return payload


def _jersey_map(events: list, t1: int, t2: int) -> dict:
    """pid -> {'jersey': int, 'team': 'home'|'away'} for every player the
    event log references (event refs can outlive the current roster — season
    rollover duplicates, transfers — so resolve from the refs, not the roster)."""
    pids = set()
    for ev in events:
        for c in ("primary_player_id", "pass_from_id", "rebound_by_id",
                  "blocked_by_id", "stolen_by_id", "secondary_player_id"):
            if ev[c]:
                pids.add(ev[c])
    if not pids:
        return {}
    ph = ",".join("?" * len(pids))
    rows = query(f"SELECT id, number, team_id FROM players WHERE id IN ({ph})",
                 tuple(pids))
    out = {}
    for r in rows:
        side = "home" if r["team_id"] == t1 else ("away" if r["team_id"] == t2 else None)
        if side:
            out[r["id"]] = {"jersey": int(r["number"] or 0), "team": side}
    return out


def _num(pmap: dict, pid) -> str | None:
    p = pmap.get(pid)
    return f"#{p['jersey']}" if p else None


def _play_text(ev: dict, pmap: dict) -> str | None:
    """One public play-by-play line, jersey numbers only."""
    who = _num(pmap, ev["primary_player_id"])
    if not who:
        return None
    et = ev["event_type"]
    if et == "shot":
        txt = f"{who} {ev['shot_type'] or 2}PT {'make' if ev['shot_result'] == 'make' else 'miss'}"
        if ev["shot_result"] == "make" and _num(pmap, ev["pass_from_id"]):
            txt += f" (assist {_num(pmap, ev['pass_from_id'])})"
        if ev["shot_result"] != "make" and _num(pmap, ev["blocked_by_id"]):
            txt += f" (block {_num(pmap, ev['blocked_by_id'])})"
        if ev["shot_result"] != "make" and _num(pmap, ev["rebound_by_id"]):
            txt += f" (reb {_num(pmap, ev['rebound_by_id'])})"
        return txt
    if et == "free_throw":
        return f"{who} FT {'make' if ev['shot_result'] == 'make' else 'miss'}"
    if et == "foul":
        on = _num(pmap, ev["secondary_player_id"])
        return f"{who} foul" + (f" (on {on})" if on else "")
    if et == "turnover":
        stl = _num(pmap, ev["stolen_by_id"])
        return f"{who} turnover" + (f" (steal {stl})" if stl else "")
    return None


def _officials_detail(game_id: int, events: list, pmap: dict) -> list:
    """Anonymized crew for the assigner view: per slot the foul count TOTAL,
    by quarter, and by charged side (home/away = the fouler's team). Order =
    explicit game_lineup_officials.slot when set, else first-seen (id) order —
    the default alignment. Names never enter the payload."""
    crew = query(
        "SELECT official_id FROM game_lineup_officials WHERE game_id=? "
        "ORDER BY (slot IS NULL), slot, id", (game_id,))
    stats: dict[int, dict] = {
        r["official_id"]: {"fouls": 0, "home": 0, "away": 0, "q": {}}
        for r in crew}
    for ev in events:
        s = stats.get(ev["official_id"]) if ev["event_type"] == "foul" else None
        if s is None:
            continue
        s["fouls"] += 1
        s["q"][str(ev["quarter"])] = s["q"].get(str(ev["quarter"]), 0) + 1
        side = pmap.get(ev["primary_player_id"], {}).get("team")
        if side:
            s[side] += 1
    out = []
    for i, r in enumerate(crew):
        label = _SLOT_LABELS[i] if i < len(_SLOT_LABELS) else f"U{i}"
        out.append({"slot": label, **stats[r["official_id"]]})
    return out


def _wp_series(score_trace: list, final: bool) -> list:
    """Win-probability strip from the (elapsed, margin) scoring trace. Uses the
    shared WP model (helpers/win_probability). Total game length = regulation
    or through the deepest period seen; a FINAL game's last point collapses to
    the winner. Score/clock derived only — public-safe."""
    if len(score_trace) < 2:
        return []
    max_t = max(t for t, _ in score_trace)
    total = float(WP.GAME_SECONDS)
    q = 4
    while total < max_t:            # stretch for OT periods actually played
        q += 1
        total = ST.q_base(q) + ST.q_len(q)
    pts = [{"t": round(t), "p": round(WP.win_prob(m, total - t, total), 3)}
           for t, m in score_trace]
    if final:
        m = score_trace[-1][1]
        pts.append({"t": round(total),
                    "p": 1.0 if m > 0 else (0.0 if m < 0 else 0.5)})
    # cap the payload — keep every late point, thin the early ones
    if len(pts) > 150:
        head, tail = pts[:-50], pts[-50:]
        pts = head[::2] + tail
    return pts


def _build_state(g: dict) -> dict:
    gid, t1, t2 = g["id"], g["team1_id"], g["team2_id"]
    events = [dict(e) for e in query(
        "SELECT id, event_type, quarter, time, primary_player_id, shot_result, "
        "       shot_type, shot_x, shot_y, pass_from_id, rebound_by_id, "
        "       blocked_by_id, stolen_by_id, secondary_player_id, official_id "
        "FROM game_events WHERE game_id=? ORDER BY id", (gid,))]
    pmap = _jersey_map(events, t1, t2)

    # single pass: box lines, score, quarter scores, team fouls, pbp, shots
    box: dict[int, dict] = {}     # pid -> line
    pts = {"home": 0, "away": 0}
    quarters: dict[str, dict] = {}
    team_fouls: dict[str, dict] = {}
    plays, shots = [], []
    score_trace = [(0.0, 0.0)]    # (elapsed secs, home margin) for the WP strip

    def line(pid):
        if pid not in box:
            p = pmap[pid]
            box[pid] = {"jersey": p["jersey"], "team": p["team"], "pts": 0,
                        "fgm": 0, "fga": 0, "fgm3": 0, "fga3": 0,
                        "ftm": 0, "fta": 0, "reb": 0, "ast": 0, "stl": 0,
                        "blk": 0, "tov": 0, "pf": 0, "on": False}
        return box[pid]

    for ev in events:
        side = pmap.get(ev["primary_player_id"], {}).get("team")
        et, make = ev["event_type"], ev["shot_result"] == "make"
        if side:
            ln = line(ev["primary_player_id"])
            if et == "shot":
                three = ev["shot_type"] == 3
                ln["fga"] += 1
                ln["fga3"] += 1 if three else 0
                if make:
                    ln["fgm"] += 1
                    ln["fgm3"] += 1 if three else 0
                    got = 3 if three else 2
                    ln["pts"] += got
                    pts[side] += got
                    q = quarters.setdefault(str(ev["quarter"]), {"home": 0, "away": 0})
                    q[side] += got
                    score_trace.append((ST.elapsed(ev["quarter"], ev["time"]),
                                        pts["home"] - pts["away"]))
                if ev["shot_x"] is not None and ev["shot_y"] is not None:
                    shots.append({"x": ev["shot_x"], "y": ev["shot_y"],
                                  "make": make, "type": 3 if three else 2,
                                  "team": side, "jersey": ln["jersey"], "q": ev["quarter"]})
            elif et == "free_throw":
                ln["fta"] += 1
                if make:
                    ln["ftm"] += 1
                    ln["pts"] += 1
                    pts[side] += 1
                    q = quarters.setdefault(str(ev["quarter"]), {"home": 0, "away": 0})
                    q[side] += 1
                    score_trace.append((ST.elapsed(ev["quarter"], ev["time"]),
                                        pts["home"] - pts["away"]))
            elif et == "turnover":
                ln["tov"] += 1
            elif et == "foul":
                ln["pf"] += 1
                tf = team_fouls.setdefault(str(ev["quarter"]), {"home": 0, "away": 0})
                tf[side] += 1
        for col, stat in (("rebound_by_id", "reb"), ("pass_from_id", None),
                          ("blocked_by_id", "blk"), ("stolen_by_id", "stl")):
            pid = ev[col]
            if pid in pmap:
                if col == "pass_from_id":
                    if et == "shot" and make:
                        line(pid)["ast"] += 1
                elif stat:
                    line(pid)[stat] += 1
        txt = _play_text(ev, pmap)
        if txt:
            plays.append({"q": ev["quarter"], "t": ev["time"],
                          "team": side, "text": txt})

    # who's on the floor now = the last event's lineup snapshot
    if events:
        for r in query("SELECT player_id FROM game_event_lineup WHERE event_id=?",
                       (events[-1]["id"],)):
            if r["player_id"] in pmap:
                line(r["player_id"])["on"] = True

    status = "final" if g["tracked"] else ("live" if events else "pregame")
    last = events[-1] if events else None
    home_box = sorted((ln for ln in box.values() if ln["team"] == "home"),
                      key=lambda ln: (-ln["pts"], ln["jersey"]))
    away_box = sorted((ln for ln in box.values() if ln["team"] == "away"),
                      key=lambda ln: (-ln["pts"], ln["jersey"]))
    return {
        "status": status,
        "date": g["date"], "location": g["location"] or "",
        "home": {"name": g["home_name"], "pts": pts["home"], "id": t1},
        "away": {"name": g["away_name"], "pts": pts["away"], "id": t2},
        "quarter": last["quarter"] if last else 1,
        "clock": last["time"] if last else "",
        "quarters": quarters,
        "team_fouls": team_fouls,
        "box": {"home": home_box, "away": away_box},
        "plays": plays[-250:][::-1],   # newest first, capped
        "shots": shots,
        "officials": _officials_detail(gid, events, pmap),
        "wp": _wp_series(score_trace, status == "final"),
        "version": (events[-1]["id"] if events else 0) * 10 + (1 if g["tracked"] else 0),
    }
