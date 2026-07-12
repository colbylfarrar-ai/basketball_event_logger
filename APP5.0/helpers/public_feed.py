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

import time

from database.db import query

CACHE_TTL = 3.0          # seconds; fan polling is decoupled from DB reads
_CACHE: dict[str, tuple[float, dict]] = {}

# crew-slot labels in assigning order; slot column 1-based, extras become U3…
_SLOT_LABELS = ("R", "U1", "U2", "U3", "U4")


def clear_cache() -> None:
    _CACHE.clear()


def state_by_token(token: str) -> dict | None:
    """Public payload for a share token, or None (unknown token OR a game the
    coach has not made public — identical outcome, no existence leak)."""
    token = (token or "").strip()
    if not token:
        return None
    hit = _CACHE.get(token)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL:
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
    _CACHE[token] = (now, payload)
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


def _officials_line(game_id: int, events: list) -> list:
    """Anonymized crew: [{'slot': 'R', 'fouls': 7}, …]. Order = explicit
    game_lineup_officials.slot when set, else first-seen (id) order — the
    default alignment. Names never enter the payload."""
    crew = query(
        "SELECT official_id FROM game_lineup_officials WHERE game_id=? "
        "ORDER BY (slot IS NULL), slot, id", (game_id,))
    calls: dict[int, int] = {}
    for ev in events:
        if ev["event_type"] == "foul" and ev["official_id"]:
            calls[ev["official_id"]] = calls.get(ev["official_id"], 0) + 1
    out = []
    for i, r in enumerate(crew):
        label = _SLOT_LABELS[i] if i < len(_SLOT_LABELS) else f"U{i}"
        out.append({"slot": label, "fouls": calls.get(r["official_id"], 0)})
    return out


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
        "home": {"name": g["home_name"], "pts": pts["home"]},
        "away": {"name": g["away_name"], "pts": pts["away"]},
        "quarter": last["quarter"] if last else 1,
        "clock": last["time"] if last else "",
        "quarters": quarters,
        "team_fouls": team_fouls,
        "box": {"home": home_box, "away": away_box},
        "plays": plays[-250:][::-1],   # newest first, capped
        "shots": shots,
        "officials": _officials_line(gid, events),
        "version": (events[-1]["id"] if events else 0) * 10 + (1 if g["tracked"] else 0),
    }
