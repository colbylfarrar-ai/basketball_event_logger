"""
OSSAA importer -- Phase 2 DB-write engine.

Turns a scrape Plan (built by tools/ossaa_import) into teams + games rows in the
ACTIVE-season DB. Properties:

  * Idempotent  -- re-running never double-inserts a game and never overwrites an
                   existing one (so a tracked game's scores are always safe).
  * Self-healing schema -- adds teams.ossaa_id on first use, so it needs no edit
                   to database/db.py's migration list.
  * Reconciling -- a team is matched by OSSAA id first, then exact name; a
                   name-matched row missing an ossaa_id gets it back-filled.

A "Plan" here is duck-typed: any object with
    .teams : dict[name -> (class, gender, ossaa_id|None)]
    .games : list[(date, home_name, away_name, home_score, away_score, tracked)]
which is exactly what tools.ossaa_import.Plan exposes.
"""
from __future__ import annotations

import re
import sqlite3

from database import db

# Tokens dropped when comparing a school's "identity" words (so "Riverside
# Eagles" and "RIVERSIDE Boys" still share the token RIVERSIDE).
_STOP_TOKENS = {"BOYS", "GIRLS", "HS", "HIGH", "SCHOOL", "THE", "OF"}


def _norm_tokens(name: str) -> set:
    return {t for t in re.findall(r"[A-Za-z0-9]+", name.upper())
            if t not in _STOP_TOKENS}


# --------------------------------------------------------------------------- #
def ensure_schema() -> None:
    """Add teams.ossaa_id (+ a partial-unique index) if missing. Idempotent.

    Mirrors db.py's own migration style: each DDL is wrapped so a re-run (column
    already present) is a no-op instead of an error.
    """
    try:
        db.execute("ALTER TABLE teams ADD COLUMN ossaa_id INTEGER")
    except sqlite3.OperationalError:
        pass  # duplicate column -> already migrated
    try:
        # Home state (default OK). Normally added by db.py's migration list; ensured
        # here too so the importer is self-sufficient if it runs first.
        db.execute("ALTER TABLE teams ADD COLUMN state TEXT NOT NULL DEFAULT 'OK'")
    except sqlite3.OperationalError:
        pass
    try:
        # NULL ossaa_id is allowed for many teams (non-OSSAA opponents); a partial
        # unique index keeps real ids unique without blocking those NULLs.
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_ossaa_id "
                   "ON teams(ossaa_id) WHERE ossaa_id IS NOT NULL")
    except sqlite3.OperationalError:
        pass


# --------------------------------------------------------------------------- #
def get_or_create_team(name: str, klass: str, gender: str, ossaa_id=None, state="OK"):
    """Return (team_id, 'matched'|'created').

    Match priority: ossaa_id, then exact name. On a name match that lacks an
    ossaa_id we back-fill it. class/gender/state of an existing team are never
    touched (the user may have corrected them).
    """
    if ossaa_id:
        r = db.query("SELECT id FROM teams WHERE ossaa_id=?", (ossaa_id,))
        if r:
            return r[0]["id"], "matched"

    # Case-insensitive so a hand-entered "riverside boys" merges with the
    # importer's "RIVERSIDE Boys" instead of duplicating (teams.name is BINARY).
    r = db.query("SELECT id, ossaa_id FROM teams WHERE name=? COLLATE NOCASE", (name,))
    if r:
        tid = r[0]["id"]
        if ossaa_id and not r[0]["ossaa_id"]:
            db.execute("UPDATE teams SET ossaa_id=? WHERE id=?", (ossaa_id, tid))
        return tid, "matched"

    try:
        tid = db.execute(
            "INSERT INTO teams (name, class, gender, ossaa_id, state) VALUES (?,?,?,?,?)",
            (name, klass, gender, ossaa_id, state))
        return tid, "created"
    except sqlite3.IntegrityError:
        # UNIQUE(name) collision (case-variant, or two schools that resolve to the
        # same suffixed name). Treat as an existing team rather than aborting the
        # whole import batch.
        r = db.query("SELECT id FROM teams WHERE name=? COLLATE NOCASE", (name,))
        if r:
            return r[0]["id"], "matched"
        raise


def game_exists(team1_id: int, team2_id: int, date: str, season: str = "Current") -> bool:
    """True if that matchup already exists on that date IN THIS SEASON, either
    home/away order. Season-scoped so the same fixture can legitimately recur in a
    later season (and so a post-rollover re-import isn't blocked by an archived row)."""
    r = db.query(
        "SELECT id FROM games WHERE date=? AND season=? AND "
        "((team1_id=? AND team2_id=?) OR (team1_id=? AND team2_id=?))",
        (date, season, team1_id, team2_id, team2_id, team1_id))
    return bool(r)


# --------------------------------------------------------------------------- #
def reconcile(plan) -> dict:
    """Classify every team in the plan against the current DB, WITHOUT writing.

    Returns {'auto': [names], 'new': [names], 'ambiguous': [rows]} where an
    'ambiguous' row resembles an existing team (same gender, shares an identity
    token) but matches neither by ossaa_id nor exact name — so it's the coach's
    call whether to merge or create. Each carries up to 5 ranked candidates:
        {name, class, gender, ossaa_id, state, candidates:[{id,name,class,shared}]}
    """
    ensure_schema()
    existing = db.query("SELECT id, name, class, gender, ossaa_id FROM teams")
    by_oid = {e["ossaa_id"] for e in existing if e["ossaa_id"] is not None}
    by_name = {e["name"].upper() for e in existing}
    toks_by_gender = {}
    for e in existing:
        toks_by_gender.setdefault(e["gender"], []).append((e, _norm_tokens(e["name"])))

    auto, new, ambiguous = [], [], []
    for name, (klass, gender, oid, state) in plan.teams.items():
        if (oid is not None and oid in by_oid) or name.upper() in by_name:
            auto.append(name)
            continue
        want = _norm_tokens(name)
        cands = []
        for e, etoks in toks_by_gender.get(gender, []):
            if e["name"].upper() == name.upper():
                continue
            shared = want & etoks
            if shared:
                cands.append({"id": e["id"], "name": e["name"], "class": e["class"],
                              "shared": sorted(shared)})
        cands.sort(key=lambda c: -len(c["shared"]))
        if cands:
            ambiguous.append({"name": name, "class": klass, "gender": gender,
                              "ossaa_id": oid, "state": state, "candidates": cands[:5]})
        else:
            new.append(name)
    return {"auto": auto, "new": new, "ambiguous": ambiguous}


# --------------------------------------------------------------------------- #
def ingest(plan, overrides=None) -> dict:
    """Write a Plan to the active DB. Returns counts. Safe to call repeatedly.

    Games are inserted with tracked=0 and season='Current'. Already-present games
    are skipped, never overwritten.

    `overrides` = {plan_team_name: existing_team_id} from reconcile()'s ambiguous
    list — the coach's case-by-case "merge this OSSAA team onto that existing
    team" decisions. A mapped team reuses the chosen row (back-filling its
    ossaa_id) instead of being created fresh.
    """
    ensure_schema()
    overrides = overrides or {}

    team_id, created_t, matched_t = {}, 0, 0
    for name, (klass, gender, oid, state) in plan.teams.items():
        mapped = overrides.get(name)
        if mapped:
            if oid:  # back-fill the OSSAA id onto the team the coach picked
                ex = db.query("SELECT ossaa_id FROM teams WHERE id=?", (mapped,))
                if ex and not ex[0]["ossaa_id"]:
                    db.execute("UPDATE teams SET ossaa_id=? WHERE id=?", (oid, mapped))
            team_id[name] = mapped
            matched_t += 1
            continue
        tid, how = get_or_create_team(name, klass, gender, oid, state)
        team_id[name] = tid
        if how == "created":
            created_t += 1
        else:
            matched_t += 1

    inserted, skipped = 0, 0
    for date, home, away, hs, as_, tracked in plan.games:
        h, a = team_id[home], team_id[away]
        iso = db.normalize_date(date)
        if game_exists(h, a, iso):
            skipped += 1
            continue
        db.execute(
            "INSERT INTO games (team1_id, team2_id, date, location, "
            "home_score, away_score, tracked, season) VALUES (?,?,?,?,?,?,?,?)",
            (h, a, iso, None, hs, as_, tracked, "Current"))
        inserted += 1

    return {"teams_created": created_t, "teams_matched": matched_t,
            "games_inserted": inserted, "games_skipped": skipped}
