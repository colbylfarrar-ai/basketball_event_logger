"""
game_dedup.py — collapse duplicate tracked games of the SAME real game.

When Coach A and Coach B both track one physical game, two ``games`` rows exist
(one per coach), each with its own event log. The shared pool should surface ONE
canonical row — the most thoroughly tracked — so coaches don't see two different
stat lines for the same game and league aggregations don't double-count it.

The pick is a SINGLE canonical game per matchup, shown to everyone (not "your own
track" — that was the rejected first cut, since it made two coaches see two
different stats). Priority, highest first:

  1. an explicit ADMIN OVERRIDE   (``app_settings`` ``gamepick:<key>`` -> game_id)
  2. the MOST DETAILED game by detail-density — coverage of the optional tracking
     fields where they apply, NOT raw event volume, so a thorough 170-event game
     beats a bare-bones 171-event one
  3. tie-break: more events, then highest id (stable; newest wins)

Pure read helpers over ``database.db`` (Streamlit-free). ``representative_game_ids``
is a no-op when nothing is double-tracked (the common case), so it is safe to drop
into the entitlement read-filters.
"""
from __future__ import annotations

from database.db import query, execute

_OVERRIDE_PREFIX = "gamepick:"

# Weight per detail signal; each rate is in [0,1] so a game's score lands in
# [0, sum(weights)]. shot (x,y) coords are weighted highest — they're the richest,
# most effortful signal and the hardest to fill in by accident.
_DETAIL_WEIGHTS = {
    "shot_xy": 3.0,     # tap-captured court coordinates on shots
    "creation": 2.0,    # who passed to / created the shot
    "defense": 2.0,     # who was guarding
    "rebound": 1.0,     # who grabbed a missed-shot rebound
    "steal": 1.0,       # who got the steal on a turnover
    "officials": 1.0,   # which official called a foul
}
_MAX_SCORE = sum(_DETAIL_WEIGHTS.values())


def matchup_key(date, team1_id, team2_id) -> str:
    """Stable, home/away-agnostic key for 'the same real game'. Team ids already
    encode gender (Boys and Girls are separate team rows), so date + the unordered
    team pair is enough; two coaches who enter home/away from opposite points of
    view still collapse to the same key."""
    a, b = sorted((int(team1_id), int(team2_id)))
    return f"{date}|{a}|{b}"


def detail_scores(game_ids) -> dict[int, dict]:
    """``{game_id: {'score': float, 'events': int}}`` over the given ids.

    One GROUP BY over ``game_events``; the per-signal rates are divided in Python
    with guarded denominators (a game with no shots simply scores 0 on shot
    signals rather than erroring). Games with zero events score 0.
    """
    ids = [int(g) for g in game_ids]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    rows = query(
        f"""SELECT game_id,
              COUNT(*)                                                            AS n,
              SUM(event_type='shot')                                              AS shots,
              SUM(event_type='shot' AND shot_x IS NOT NULL AND shot_y IS NOT NULL) AS shot_xy,
              SUM(event_type='shot' AND (shot_created_by_id IS NOT NULL
                                         OR pass_from_id IS NOT NULL))            AS shot_create,
              SUM(guarded_by_id IS NOT NULL)                                      AS guarded,
              SUM(event_type='shot' AND shot_result='miss')                       AS misses,
              SUM(event_type='shot' AND shot_result='miss'
                  AND rebound_by_id IS NOT NULL)                                  AS reb,
              SUM(event_type='turnover')                                          AS tovs,
              SUM(event_type='turnover' AND stolen_by_id IS NOT NULL)             AS steals,
              SUM(event_type='foul')                                              AS fouls,
              SUM(event_type='foul' AND official_id IS NOT NULL)                  AS off_fouls
            FROM game_events WHERE game_id IN ({ph}) GROUP BY game_id""",
        tuple(ids))
    out: dict[int, dict] = {}
    for r in rows:
        def rate(num_key, den_key):
            den = r[den_key] or 0
            return (r[num_key] or 0) / den if den else 0.0
        score = (
            _DETAIL_WEIGHTS["shot_xy"]   * rate("shot_xy", "shots") +
            _DETAIL_WEIGHTS["creation"]  * rate("shot_create", "shots") +
            _DETAIL_WEIGHTS["defense"]   * rate("guarded", "n") +
            _DETAIL_WEIGHTS["rebound"]   * rate("reb", "misses") +
            _DETAIL_WEIGHTS["steal"]     * rate("steals", "tovs") +
            _DETAIL_WEIGHTS["officials"] * rate("off_fouls", "fouls")
        )
        out[int(r["game_id"])] = {"score": round(score, 4), "events": int(r["n"] or 0)}
    for gid in ids:                       # zero-event games never hit the GROUP BY
        out.setdefault(gid, {"score": 0.0, "events": 0})
    return out


def _overrides() -> dict[str, int]:
    """Admin matchup overrides: ``{matchup_key: game_id}``."""
    out: dict[str, int] = {}
    for r in query("SELECT key, value FROM app_settings WHERE key LIKE ?",
                   (_OVERRIDE_PREFIX + "%",)):
        v = (r["value"] or "").strip()
        if v.isdigit():
            out[r["key"][len(_OVERRIDE_PREFIX):]] = int(v)
    return out


def set_override(key: str, game_id) -> None:
    """Pin a matchup to a specific game id (admin). Pass through ``matchup_key``."""
    execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            (_OVERRIDE_PREFIX + key, str(int(game_id))))


def clear_override(key: str) -> None:
    """Drop a matchup override → revert to the automatic most-detailed pick."""
    execute("DELETE FROM app_settings WHERE key=?", (_OVERRIDE_PREFIX + key,))


def representative_game_ids(game_ids) -> set[int]:
    """Reduce a set of tracked game ids to ONE canonical game per matchup.

    No-op (returns the input set unchanged) when nothing is double-tracked, so it
    is cheap and safe to wrap the entitlement read-filters with it. ``None`` is the
    caller's concern (admin/unrestricted) — this only ever receives a concrete set.
    """
    ids = {int(g) for g in game_ids}
    if len(ids) <= 1:
        return ids
    ph = ",".join("?" * len(ids))
    meta = {int(r["id"]): r for r in query(
        f"SELECT id, date, team1_id, team2_id FROM games WHERE id IN ({ph})",
        tuple(ids))}
    groups: dict[str, list[int]] = {}
    for gid in ids:
        m = meta.get(gid)
        if not m:                          # unknown id — leave it alone
            groups[f"_solo_{gid}"] = [gid]
            continue
        groups.setdefault(matchup_key(m["date"], m["team1_id"], m["team2_id"]), []).append(gid)
    if all(len(v) == 1 for v in groups.values()):
        return ids                          # fast path: no duplicates
    ov = _overrides()
    dup_ids = [g for v in groups.values() if len(v) > 1 for g in v]
    scores = detail_scores(dup_ids)
    keep: set[int] = set()
    for key, members in groups.items():
        if len(members) == 1:
            keep.add(members[0])
            continue
        if key in ov and ov[key] in members:        # 1. admin override
            keep.add(ov[key])
            continue
        # 2. most detailed, 3. tie-break events then id
        keep.add(max(members, key=lambda g: (scores.get(g, {}).get("score", 0.0),
                                              scores.get(g, {}).get("events", 0), g)))
    return keep


def duplicate_matchups() -> list[dict]:
    """Matchups tracked more than once, for the admin resolve-duplicates UI. Each:
    ``{key, date, team1, team2, candidates:[{game_id, tracked_by, in_pool, score,
    events}], override}``; candidates sorted best-first (current auto-pick = [0])."""
    rows = query("SELECT id, date, team1_id, team2_id, tracked_by, in_pool "
                 "FROM games WHERE tracked=1")
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(matchup_key(r["date"], r["team1_id"], r["team2_id"]), []).append(r)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    if not dups:
        return []
    scores = detail_scores([r["id"] for v in dups.values() for r in v])
    ov = _overrides()
    names = {r["id"]: r["name"] for r in query("SELECT id, name FROM teams")}
    out: list[dict] = []
    for key, members in dups.items():
        cand = [{
            "game_id": r["id"], "tracked_by": r["tracked_by"] or "—",
            "in_pool": bool(r["in_pool"]),
            "score": scores.get(r["id"], {}).get("score", 0.0),
            "events": scores.get(r["id"], {}).get("events", 0),
        } for r in members]
        cand.sort(key=lambda c: (-c["score"], -c["events"], c["game_id"]))
        m0 = members[0]
        out.append({
            "key": key, "date": m0["date"],
            "team1": names.get(m0["team1_id"], m0["team1_id"]),
            "team2": names.get(m0["team2_id"], m0["team2_id"]),
            "candidates": cand, "override": ov.get(key),
        })
    out.sort(key=lambda d: d["date"], reverse=True)
    return out
