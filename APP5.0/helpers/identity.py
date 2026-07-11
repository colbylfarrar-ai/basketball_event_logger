"""
identity.py — cross-season player identity (Tier 3, ML_LAYER_ROADMAP).

The New Season rollover archives the old roster (`players.archived=1`, season
stamped) and a returning player gets a BRAND-NEW `players.id` next season, so
nothing links a person year over year. This adds a stable PERSON key:

  • `players.identity_id` (nullable) — when set, this row IS the same person as the
    row whose key it points at. NULL = the player is their own identity.
  • a person is resolved as COALESCE(identity_id, id) — so unmatched players need no
    backfill, and the link chains across seasons (year 3 → year 2's identity → …).

This module is the engine behind the New-Season "Returning players" match UI:
suggest likely matches (name + number) between this season's roster and the team's
archived rows, and set/clear the link. Streamlit-free; pure data. The cross-season
DEVELOPMENT analytics (YoY trajectory, projection) build on top once a 2nd tracked
season is linked — they are deliberately not here yet (no data to chart until then).
"""
from __future__ import annotations

import difflib

from database.db import query, execute


def person_key_sql(alias="p"):
    """SQL fragment resolving a player row to its stable person key."""
    return f"COALESCE({alias}.identity_id, {alias}.id)"


def _norm(s):
    """Lowercase alphanumerics only — robust name compare ('J. Smith' ~ 'john smith')."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def prior_identities(team_id):
    """Archived (past-season) players for a team, collapsed to ONE row per person
    (the newest season each identity appears in). Each carries `_key` = the person
    key to link a current row to. These are the candidates to match against."""
    rows = query(
        "SELECT id, name, number, season, identity_id FROM players "
        "WHERE team_id=? AND archived=1", (team_id,))
    by_key = {}
    for r in rows:
        k = r["identity_id"] or r["id"]
        prev = by_key.get(k)
        if prev is None or (r["season"] or "") > (prev["season"] or ""):
            by_key[k] = {**r, "_key": k}
    return list(by_key.values())


def _score(cur, prior):
    """Match score in [0,1]: 0.7 name-similarity + 0.3 same-number bonus."""
    nm = difflib.SequenceMatcher(None, _norm(cur["name"]), _norm(prior["name"])).ratio()
    num = 0.3 if (cur.get("number") is not None
                  and cur.get("number") == prior.get("number")) else 0.0
    return nm, round(0.7 * nm + num, 3)


def suggest_matches(team_id, cutoff=0.55, top=3):
    """For this season's roster (archived=0), suggest prior-season identities to
    link to. Returns [{pid, name, number, linked_to, candidates:[{identity_key,
    name, number, season, score}]}], best candidate first. `linked_to` = the person
    key this row is ALREADY linked to (None when it's its own identity)."""
    current = query(
        "SELECT id, name, number, identity_id FROM players "
        "WHERE team_id=? AND archived=0 ORDER BY number, name", (team_id,))
    priors = prior_identities(team_id)
    out = []
    for c in current:
        cands = []
        for p in priors:
            nm, sc = _score(c, p)
            if nm >= 0.8 or sc >= cutoff:
                cands.append({"identity_key": p["_key"], "name": p["name"],
                              "number": p["number"], "season": p["season"],
                              "score": sc})
        cands.sort(key=lambda x: -x["score"])
        out.append({
            "pid": c["id"], "name": c["name"], "number": c["number"],
            "linked_to": (c["identity_id"] if c["identity_id"]
                          and c["identity_id"] != c["id"] else None),
            "candidates": cands[:top],
        })
    return out


def transfer_search(name_query, exclude_team_id=None, limit=8, cutoff=0.4):
    """League-wide fuzzy lookup of ARCHIVED players for a TRANSFER-IN link — a player
    whose prior-season row is on ANOTHER team. Coach-initiated (typed), never an auto
    cross-team suggestion (auto would false-link every same name). Returns
    [{identity_key, name, number, team, season, score}] best first, one row per
    person (newest season), optionally excluding the current team.

    The link itself is team-agnostic (identity_id points at a person key), so once
    linked the transfer's identity_history spans both schools."""
    q = _norm(name_query)
    if not q:
        return []
    rows = query(
        "SELECT p.id, p.name, p.number, p.season, p.identity_id, t.name AS team, "
        "p.team_id FROM players p JOIN teams t ON t.id=p.team_id WHERE p.archived=1")
    by_key = {}
    for r in rows:
        if exclude_team_id is not None and r["team_id"] == exclude_team_id:
            continue
        k = r["identity_id"] or r["id"]
        prev = by_key.get(k)
        if prev is None or (r["season"] or "") > (prev["season"] or ""):
            by_key[k] = {**r, "_key": k}
    out = []
    for r in by_key.values():
        sc = difflib.SequenceMatcher(None, q, _norm(r["name"])).ratio()
        if sc >= cutoff:
            out.append({"identity_key": r["_key"], "name": r["name"],
                        "number": r["number"], "team": r["team"],
                        "season": r["season"], "score": round(sc, 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def link(current_pid, identity_key):
    """Mark `current_pid` as the same person as `identity_key` (a prior row's key)."""
    execute("UPDATE players SET identity_id=? WHERE id=?",
            (int(identity_key), int(current_pid)))


def unlink(current_pid):
    """Reset `current_pid` to its own identity (clears the link)."""
    execute("UPDATE players SET identity_id=NULL WHERE id=?", (int(current_pid),))


def propagate_person_fields(pid):
    """Copy PERSON-level fields (name; grad_year when set) from row `pid` to every
    other season-row of the same person. A player's name/class don't change season
    to season — they're duplicated per-row by the rollover — so an edit on any one
    row is the person's truth. grad_year only propagates when non-NULL (a source
    row that never had one set must not wipe a year a past row knows).
    Returns the number of sibling rows updated."""
    r = query("SELECT name, grad_year, COALESCE(identity_id, id) AS k "
              "FROM players WHERE id=?", (int(pid),))
    if not r:
        return 0
    name, gy, key = r[0]["name"], r[0]["grad_year"], r[0]["k"]
    sibs = query("SELECT id FROM players WHERE COALESCE(identity_id, id)=? AND id!=?",
                 (key, int(pid)))
    if not sibs:
        return 0
    if gy is None:
        execute("UPDATE players SET name=? "
                "WHERE COALESCE(identity_id, id)=? AND id!=?",
                (name, key, int(pid)))
    else:
        execute("UPDATE players SET name=?, grad_year=? "
                "WHERE COALESCE(identity_id, id)=? AND id!=?",
                (name, gy, key, int(pid)))
    return len(sibs)


def auto_link(pid):
    """Best-effort identity link for a row just created onto a DIFFERENT season
    (retro-add): if exactly ONE person on the same team, in another season,
    carries the same normalized name, link the new row to that person — so a
    retro-added returner never becomes a duplicate person. Ambiguous (two
    same-name persons) or no match -> leave unlinked. Returns the person key
    linked to, or None."""
    r = query("SELECT team_id, name, season FROM players WHERE id=?", (int(pid),))
    if not r:
        return None
    team_id, name, season = r[0]["team_id"], r[0]["name"], r[0]["season"]
    rows = query(
        "SELECT id, name, identity_id FROM players "
        "WHERE team_id=? AND id!=? AND season!=?", (team_id, int(pid), season))
    keys = {(x["identity_id"] or x["id"]) for x in rows
            if _norm(x["name"]) == _norm(name)}
    if len(keys) != 1:
        return None
    key = keys.pop()
    link(pid, key)
    # inherit the person's known grad_year (the new row got an auto default that
    # assumed a brand-new freshman — the linked person's real class year wins)
    sib = query(
        "SELECT grad_year FROM players WHERE COALESCE(identity_id, id)=? "
        "AND id!=? AND grad_year IS NOT NULL "
        "ORDER BY archived ASC, season DESC LIMIT 1", (key, int(pid)))
    if sib:
        execute("UPDATE players SET grad_year=? WHERE id=?",
                (sib[0]["grad_year"], int(pid)))
    return key


def sync_person_fields():
    """One-shot backfill: for every linked person with rows in 2+ seasons, copy
    the freshest row's name (live archived=0 row first, else newest season) onto
    the older rows, and spread the freshest non-NULL grad_year. Fixes rosters
    renamed on the current season AFTER a rollover (the archived rows kept the
    old names). Returns the number of rows updated."""
    rows = query("SELECT id, name, grad_year, archived, season, "
                 "COALESCE(identity_id, id) AS k FROM players")
    by_key = {}
    for r in rows:
        by_key.setdefault(r["k"], []).append(r)
    changed = 0
    for group in by_key.values():
        if len(group) < 2:
            continue
        # freshest row wins: the live (archived=0) row if the person is on a
        # current roster, else the newest archived season's row
        live = [r for r in group if not r["archived"]]
        src = live[0] if live else max(group, key=lambda r: r["season"] or "")
        # grad_year: src's own, else the freshest non-NULL anywhere in the chain
        gy = src["grad_year"]
        if gy is None:
            with_gy = [r for r in group if r["grad_year"] is not None]
            if with_gy:
                gy = max(with_gy, key=lambda r: (0 if r["archived"] else 1,
                                                 r["season"] or ""))["grad_year"]
        for r in group:
            if r["id"] == src["id"]:
                continue
            new_gy = gy if gy is not None else r["grad_year"]
            if r["name"] != src["name"] or r["grad_year"] != new_gy:
                execute("UPDATE players SET name=?, grad_year=? WHERE id=?",
                        (src["name"], new_gy, r["id"]))
                changed += 1
    return changed


def identity_history(identity_key):
    """Every player row across seasons sharing `identity_key` (current + archived),
    oldest season first — the person's season-by-season footprint. Feeds the future
    cross-season development view."""
    rows = query(
        "SELECT id, team_id, name, number, season, archived, identity_id "
        "FROM players WHERE COALESCE(identity_id, id)=?", (int(identity_key),))
    return sorted(rows, key=lambda r: (r["season"] or ""))
