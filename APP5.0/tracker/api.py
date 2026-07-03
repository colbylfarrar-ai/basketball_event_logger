"""
api.py — FastAPI backend for the mobile tracker PWA.

Serves the offline-first courtside logger (tracker/static/) and a small JSON
API over the SAME SQLite database the Streamlit app uses. All writes go through
helpers/game_events.py, the same code path as the Streamlit Game Tracker page,
so +/- snapshots, possession seconds and zone derivation can never drift.

Run from the repo root:
    python -m uvicorn tracker.api:app --host 0.0.0.0 --port 8500

Auth (fail-closed): every /api request needs `Authorization: Bearer <token>`.
A token resolves to a coach via app_users.tracker_token (issued on the Settings
page), or to the owner via the TRACKER_TOKEN env master. Only Paid/admin coaches
may use the tracker (no valid token = 401; a Free plan = 403). The logging coach
is stamped onto games.tracked_by for pool membership + attribution.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database.db import (execute, initialize_database, normalize_date, query,
                         set_audit_actor)
import helpers.event_log as EL
import helpers.game_events as GE
import helpers.entitlement as ENT
import helpers.seasons as SEAS

_STATIC = Path(__file__).resolve().parent / "static"

initialize_database()


# ── auth (per-coach identity; fail-closed) ─────────────────────────────────────
def _resolve_user(request: Request):
    """Bearer token -> the coach who owns it. Resolution order:
       1. a per-coach app_users.tracker_token (issued on the Settings page)
       2. the env TRACKER_TOKEN master (owner / start_tracker.ps1 bootstrap)
    Returns the user dict or None. NO token now means NO access (fail-closed)."""
    got = request.headers.get("authorization", "")
    if not got.startswith("Bearer "):
        return None
    tok = got[7:].strip()
    if not tok:
        return None
    rows = query("SELECT email, role, plan, team_id FROM app_users "
                 "WHERE tracker_token=? AND tracker_token<>''", (tok,))
    if rows:
        return dict(rows[0])
    # "assistant scorer" guest link — its own stored token; resolves to the owner
    # coach (inherits their plan so the tracker works) but flagged guest, so
    # require_full_user blocks it from anything past logging/undoing events.
    grow = query("SELECT u.email, u.role, u.plan, u.team_id "
                 "FROM tracker_guest_tokens g JOIN app_users u ON u.email=g.owner_email "
                 "WHERE g.token=? AND g.revoked=0", (tok,))
    if grow:
        u = dict(grow[0])
        u["guest"] = True
        return u
    env_tok = os.environ.get("TRACKER_TOKEN")
    if env_tok and tok == env_tok:
        return {"email": os.environ.get("TRACKER_OWNER_EMAIL", "").strip().lower(),
                "role": "admin", "plan": "paid", "team_id": None}
    return None


def current_api_user(request: Request) -> dict:
    """Gate every /api call: a valid token AND a Paid (or admin) plan — the
    tracker is a paid feature. Returns the identity so handlers can attribute
    tracked games (games.tracked_by)."""
    user = _resolve_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="bad or missing token")
    if user.get("role") != "admin" and user.get("plan") != "paid":
        raise HTTPException(status_code=403, detail="tracker requires a Paid plan")
    # attribute every tracker write this request to this coach (router-wide Depends)
    set_audit_actor(user.get("email", ""))
    return user


def require_full_user(request: Request) -> dict:
    """current_api_user + a guest block: rejects "assistant scorer" guest links so
    they can only log/undo events — never create/finish/edit/delete or change
    setup. (The router-wide current_api_user already validated the token.)"""
    user = current_api_user(request)
    if user.get("guest"):
        raise HTTPException(status_code=403,
                            detail="assistant scorer link is log-only")
    return user


# The gate guards /api only — the PWA shell (/, /static, /sw.js) must load
# without headers so the app can boot and show its token prompt.
app = FastAPI(title="HoopTracks")
api = APIRouter(prefix="/api", dependencies=[Depends(current_api_user)])


# ── request models ──────────────────────────────────────────────────────────────
class EventIn(BaseModel):
    uuid: str
    event_type: str
    quarter: int = 1
    time: str = "0:00"
    primary_player_id: int | None = None
    shot_result: str | None = None
    shot_x: float | None = None
    shot_y: float | None = None
    shot_type: int | None = None
    zone: str | None = None
    pass_from_id: int | None = None
    shot_created_by_id: int | None = None
    rebound_by_id: int | None = None
    blocked_by_id: int | None = None
    guarded_by_id: int | None = None
    secondary_player_id: int | None = None
    official_id: int | None = None
    stolen_by_id: int | None = None
    play_type: str | None = None
    defense: str | None = None
    on_court: list[int] = Field(default_factory=list)
    officials_on: list[int] = Field(default_factory=list)


class EventBatch(BaseModel):
    events: list[EventIn]


class EventEdit(BaseModel):
    """Field set the editor manages — mirrors pages/3_Event_Editor.py."""
    event_type: str
    quarter: int
    time: str
    primary_player_id: int | None = None
    shot_result: str | None = None
    shot_type: int | None = None
    zone: str | None = None
    pass_from_id: int | None = None
    shot_created_by_id: int | None = None
    rebound_by_id: int | None = None
    blocked_by_id: int | None = None
    guarded_by_id: int | None = None
    secondary_player_id: int | None = None
    official_id: int | None = None
    stolen_by_id: int | None = None
    play_type: str | None = None
    defense: str | None = None


class NewGame(BaseModel):
    team1_id: int
    team2_id: int
    date: str
    location: str | None = None
    video_url: str = ""
    # Optional season override ('Current' or a label). None -> inferred from the
    # date (Oct 1 cutoff), so a back-dated game lands in its real past season.
    season: str | None = None


class NewTeam(BaseModel):
    name: str
    klass: str = Field(default="N/A", alias="class")
    gender: str


class NewPlayer(BaseModel):
    team_id: int
    name: str
    number: int = Field(default=0, ge=0, le=999)
    height: float | None = None
    wingspan: float | None = None
    weight: float | None = None
    handedness: str = "right"


class HandednessUpdate(BaseModel):
    handedness: str


class NewOfficial(BaseModel):
    name: str
    official_id: int


def _scoreboard(game_id: int) -> dict:
    state = GE.live_state(game_id, n_events=0)
    state.pop("events", None)
    return state


# ── API routes ──────────────────────────────────────────────────────────────────
@api.get("/games")
def list_games(q: str | None = None, season: str | None = None):
    """Tracker game picker. Default = current-season tracked OR recent games,
    capped — a fast, bounded list (the OSSAA importer can hold 13k+ schedule
    rows, which froze the PWA when sent whole). Pass ?q=<text> to SEARCH every
    game of the chosen season by team name (also capped), so any game is
    reachable. ?season=<label> switches the picker to a PAST season (retro
    tracking): its games list whole — no 30-day recency rule there."""
    cols = ("g.id, g.date, g.tracked, g.team1_id AS home_id, "
            "g.team2_id AS away_id, t1.name AS home, t2.name AS away, "
            "t1.gender AS gender")
    joins = ("FROM games g JOIN teams t1 ON t1.id=g.team1_id "
             "JOIN teams t2 ON t2.id=g.team2_id")
    szn = "Current" if SEAS.is_current(season) else str(season).strip()
    q = (q or "").strip()
    if len(q) >= 2:
        like = f"%{q}%"
        games = query(
            f"SELECT {cols} {joins} WHERE g.season=? "
            "AND (t1.name LIKE ? OR t2.name LIKE ?) "
            "ORDER BY g.tracked DESC, g.date DESC, g.id DESC LIMIT 100",
            (szn, like, like))
    elif szn != "Current":
        # A past season is a finite, hand-picked set — list it whole (capped).
        games = query(
            f"SELECT {cols} {joins} WHERE g.season=? "
            "ORDER BY g.tracked DESC, g.date DESC, g.id DESC LIMIT 300", (szn,))
    else:
        # Default picker = current-season TRACKED games (resume) + recently-dated
        # games, so a just-created game appears and you can start tracking it. The
        # OSSAA schedule dump is old-dated → excluded; ?q= search reaches anything
        # else. LIMIT + the PWA's render cap keep the list freeze-proof.
        games = query(
            f"SELECT {cols} {joins} WHERE g.season='Current' "
            "AND (g.tracked=1 OR g.date >= date('now','-30 day')) "
            "ORDER BY g.tracked DESC, g.date DESC, g.id DESC LIMIT 300")
    return {"games": games}


@api.get("/seasons")
def list_seasons():
    """Season picker options for the PWA: [{value, label}], active first."""
    return {"seasons": [{"value": v, "label": l} for v, l in SEAS.season_options()]}


@api.get("/games/{game_id}")
def game_detail(game_id: int):
    g = query("""
        SELECT g.id, g.date, g.season, g.team1_id, g.team2_id, t1.name n1, t2.name n2
        FROM games g JOIN teams t1 ON t1.id=g.team1_id
                     JOIN teams t2 ON t2.id=g.team2_id WHERE g.id=?""", (game_id,))
    if not g:
        raise HTTPException(status_code=404, detail="no such game")
    g = g[0]
    # Archived players included (flagged) so the event EDITOR can resolve and
    # re-assign them — the lineup screen filters archived=1 out client-side.
    # Mirrors event_log.game_people(), which includes archived by design.
    #
    # Retro tracking: `archived` in this payload is RELATIVE TO THE GAME'S
    # SEASON — on a past-season game, that season's (rollover-archived) players
    # report archived=0 so they take the floor, while everyone else (including
    # today's active roster) reports archived=1 (pickable-but-dimmed in the
    # editor). Current games keep the raw flag, i.e. today's exact behaviour.
    players = query(
        "SELECT id, name, number, team_id, archived, season, handedness "
        "FROM players WHERE team_id IN (?,?) ORDER BY team_id, number, name",
        (g["team1_id"], g["team2_id"]))
    gszn = g["season"] or "Current"
    if not SEAS.is_current(gszn):
        players = [{**p, "archived": 0 if (p["season"] or "") == gszn else 1}
                   for p in players]
    players = [{k: v for k, v in p.items() if k != "season"} for p in players]
    # archived included (flagged) like players: the editor must resolve a ref on an
    # existing foul; the client filters archived out of the lineup picker.
    officials = query("SELECT id, name, archived FROM officials ORDER BY name")
    return {
        "id": g["id"], "date": g["date"],
        "home": {"id": g["team1_id"], "name": g["n1"]},
        "away": {"id": g["team2_id"], "name": g["n2"]},
        "players": players, "officials": officials,
    }


@api.get("/games/{game_id}/live")
def game_live(game_id: int):
    try:
        return GE.live_state(game_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="no such game")


@api.post("/games/{game_id}/events")
def post_events(game_id: int, batch: EventBatch,
                user: dict = Depends(current_api_user)):
    if not query("SELECT id FROM games WHERE id=?", (game_id,)):
        raise HTTPException(status_code=404, detail="no such game")
    pid2team = {p["id"]: p["team_id"] for p in query(
        "SELECT p.id, p.team_id FROM players p WHERE p.team_id IN "
        "(SELECT team1_id FROM games WHERE id=?) OR p.team_id IN "
        "(SELECT team2_id FROM games WHERE id=?)", (game_id, game_id))}
    results = []
    for ev in batch.events:
        if ev.event_type not in GE.EVENT_TYPES:
            results.append({"uuid": ev.uuid, "status": "rejected", "event_id": None})
            continue
        existed = query("SELECT id FROM game_events WHERE client_uuid=?", (ev.uuid,))
        on_court = [(pid, pid2team[pid]) for pid in ev.on_court if pid in pid2team]
        try:
            eid = GE.log_event(
                game_id,
                ev.model_dump(exclude={"uuid", "on_court", "officials_on"}),
                on_court, ev.officials_on, client_uuid=ev.uuid)
        except sqlite3.IntegrityError:
            # A second device won the client_uuid race after the dup-check above
            # (offline-first PWAs replay the same tap on reconnect). The unique
            # index rejected our duplicate insert — resolve to the row the winner
            # wrote so the retry stays idempotent instead of 500-ing.
            row = query("SELECT id FROM game_events WHERE client_uuid=?", (ev.uuid,))
            eid = row[0]["id"] if row else None
            existed = True
        results.append({
            "uuid": ev.uuid,
            "status": "duplicate" if existed else "inserted",
            "event_id": eid,
        })
    # Attribute the game to its logger (first event wins; never overwrites) so
    # pool membership + canonical-pick can resolve who tracked it.
    if user.get("email"):
        execute("UPDATE games SET tracked_by=? WHERE id=? "
                "AND (tracked_by IS NULL OR tracked_by='')",
                (user["email"], game_id))
    return {"results": results, "live": _scoreboard(game_id)}


@api.post("/games/{game_id}/undo")
def undo(game_id: int):
    if not query("SELECT id FROM games WHERE id=?", (game_id,)):
        raise HTTPException(status_code=404, detail="no such game")
    eid = GE.undo_last_event(game_id)
    if eid:
        GE.bump_data_version()
    return {"deleted_event_id": eid, "live": _scoreboard(game_id)}


@api.post("/games/{game_id}/finish")
def finish(game_id: int, user: dict = Depends(require_full_user)):
    if not query("SELECT id FROM games WHERE id=?", (game_id,)):
        raise HTTPException(status_code=404, detail="no such game")
    hp, ap = GE.finish_game(game_id)
    if user.get("email"):
        execute("UPDATE games SET tracked_by=? WHERE id=? "
                "AND (tracked_by IS NULL OR tracked_by='')",
                (user["email"], game_id))
        # tracked_by may have been set just now — re-derive the pooled flag from
        # this coach's Co-op toggle so the read-path sees it without delay.
        ENT.recompute_game_pool(game_id)
    GE.bump_data_version()
    return {"ok": True, "home": hp, "away": ap}


@api.get("/me")
def whoami(user: dict = Depends(current_api_user)):
    """The resolved identity — lets the PWA hide full-coach-only controls for a
    guest "assistant scorer" link (log-only). Guest-allowed (read only)."""
    return {"email": user.get("email", ""), "role": user.get("role", ""),
            "plan": user.get("plan", ""), "guest": bool(user.get("guest"))}


# ── courtside setup: create game / team, quick-add player / official ───────────
@api.get("/teams")
def list_teams():
    return {"teams": query("SELECT id, name, class, gender FROM teams ORDER BY name")}


@api.post("/teams")
def create_team(t: NewTeam, _: dict = Depends(require_full_user)):
    existing = query("SELECT id FROM teams WHERE name=?", (t.name.strip(),))
    if existing:
        return {"id": existing[0]["id"], "created": False}
    if t.gender not in ("M", "F"):
        raise HTTPException(status_code=422, detail="gender must be M or F")
    try:
        tid = execute("INSERT INTO teams (name, class, gender) VALUES (?,?,?)",
                      (t.name.strip(), t.klass, t.gender))
    except Exception:
        raise HTTPException(status_code=422, detail="invalid team (check class value)")
    GE.bump_data_version()
    return {"id": tid, "created": True}


@api.post("/games")
def create_game(g: NewGame, user: dict = Depends(require_full_user)):
    if g.team1_id == g.team2_id:
        raise HTTPException(status_code=422, detail="home and away must differ")
    date = normalize_date(g.date)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(date or "")):
        raise HTTPException(status_code=422, detail="date must be a real date")
    for tid in (g.team1_id, g.team2_id):
        if not query("SELECT id FROM teams WHERE id=?", (tid,)):
            raise HTTPException(status_code=422, detail=f"no such team {tid}")
    # season: explicit override wins, else inferred from the date (Oct 1 cutoff)
    # so a back-dated game lands directly in its real past season.
    szn = SEAS.resolve_new_game_season(date, g.season)
    gid = execute(
        "INSERT INTO games (team1_id, team2_id, date, location, video_url, tracked_by, season) "
        "VALUES (?,?,?,?,?,?,?)",
        (g.team1_id, g.team2_id, date, (g.location or "").strip() or None,
         g.video_url.strip(), (user.get("email") or ""), szn))
    GE.bump_data_version()
    return {"id": gid, "created": True, "season": szn}


@api.post("/games/{game_id}/players")
def quick_add_player(game_id: int, p: NewPlayer,
                     _: dict = Depends(require_full_user)):
    g = query("SELECT team1_id, team2_id FROM games WHERE id=?", (game_id,))
    if not g:
        raise HTTPException(status_code=404, detail="no such game")
    if p.team_id not in (g[0]["team1_id"], g[0]["team2_id"]):
        raise HTTPException(status_code=422, detail="team not in this game")
    name = p.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name required")
    # Same dup rule as the Streamlit Quick Add: a player of that name already on
    # THIS GAME'S season roster -> reuse it. A retro game adds the player to its
    # own past season (archived, so they never surface in current pickers).
    gszn = SEAS.game_season(game_id)
    rc, rp = SEAS.roster_clause(gszn)
    existing = query(f"SELECT id FROM players WHERE team_id=? AND name=? AND {rc}",
                     (p.team_id, name, *rp))
    if existing:
        return {"id": existing[0]["id"], "created": False}
    hand = "left" if p.handedness == "left" else "right"
    pid = execute(
        "INSERT INTO players (team_id, name, number, height, wingspan, weight, handedness, season, archived) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (p.team_id, name, int(p.number or 0), p.height, p.wingspan, p.weight, hand,
         gszn, 0 if SEAS.is_current(gszn) else 1))
    GE.bump_data_version()
    return {"id": pid, "created": True}


@api.post("/games/{game_id}/players/{player_id}/handedness")
def set_player_handedness(game_id: int, player_id: int, body: HandednessUpdate,
                          _: dict = Depends(require_full_user)):
    """Flip an existing player's shooting hand from the tracker roster screen."""
    g = query("SELECT team1_id, team2_id FROM games WHERE id=?", (game_id,))
    if not g:
        raise HTTPException(status_code=404, detail="no such game")
    row = query("SELECT team_id FROM players WHERE id=?", (player_id,))
    if not row or row[0]["team_id"] not in (g[0]["team1_id"], g[0]["team2_id"]):
        raise HTTPException(status_code=404, detail="player not in this game")
    hand = "left" if body.handedness == "left" else "right"
    execute("UPDATE players SET handedness=? WHERE id=?", (hand, player_id))
    GE.bump_data_version()
    return {"id": player_id, "handedness": hand}


@api.post("/officials")
def quick_add_official(o: NewOfficial, _: dict = Depends(require_full_user)):
    if not o.name.strip():
        raise HTTPException(status_code=422, detail="name required")
    # Re-adding a previously-archived ref (same official_id) revives them. Keep the
    # STORED name on collision (the caller displays it back) — only un-archive.
    execute("INSERT INTO officials (name, official_id) VALUES (?,?) "
            "ON CONFLICT(official_id) DO UPDATE SET archived=0",
            (o.name.strip(), int(o.official_id)))
    row = query("SELECT id, name FROM officials WHERE official_id=?",
                (o.official_id,))
    if not row:
        raise HTTPException(status_code=422, detail="could not save official")
    GE.bump_data_version()
    # name comes back from the DB: if the official_id already existed under a
    # different name, the caller must display the STORED name, not its input.
    return {"id": row[0]["id"], "name": row[0]["name"]}


# ── event editor (mirrors pages/3_Event_Editor.py via helpers/event_log.py) ────
def _score_in_sync(game_id: int) -> bool:
    """True when the stored final score equals the event-derived score — i.e.
    nobody has manually overridden it (Input Hub / Setup allow that)."""
    g = query("SELECT home_score, away_score FROM games WHERE id=?", (game_id,))
    derived = EL.score_from_events(game_id)
    return bool(g and derived
                and (g[0]["home_score"], g[0]["away_score"]) == derived)


def _post_edit_rescore(game_id: int, was_in_sync: bool) -> bool:
    """After an edit/delete on a FINAL game: re-freeze the stored score only if
    it was tracking the event log before the edit. A manually-corrected score
    (stored != derived pre-edit) is never silently overwritten — the old Event
    Editor page made recompute an explicit button for exactly that reason.
    Returns True when stored and derived scores still differ (drift) so the
    client can offer a manual recompute."""
    g = query("SELECT tracked FROM games WHERE id=?", (game_id,))
    if not g or not g[0]["tracked"]:
        return False
    if was_in_sync:
        EL.recompute_final_score(game_id)
        return False
    return not _score_in_sync(game_id)


@api.get("/games/{game_id}/events")
def list_events(game_id: int, quarter: int | None = None):
    if not query("SELECT id FROM games WHERE id=?", (game_id,)):
        raise HTTPException(status_code=404, detail="no such game")
    return {"events": EL.load_events(game_id, quarter)}


@api.put("/games/{game_id}/events/{event_id}")
def edit_event(game_id: int, event_id: int, vals: EventEdit,
               _: dict = Depends(require_full_user)):
    ev = query("SELECT * FROM game_events WHERE id=? AND game_id=?",
               (event_id, game_id))
    if not ev:
        raise HTTPException(status_code=404, detail="no such event")
    if vals.event_type not in EL.EVENT_TYPES:
        raise HTTPException(status_code=422, detail="bad event_type")
    pid2team = EL.game_people(game_id)["pid2team"]
    d = vals.model_dump()
    drift = False
    if EL.event_changed(ev[0], d):
        was_in_sync = _score_in_sync(game_id)
        EL.update_event(game_id, event_id, d, pid2team)
        drift = _post_edit_rescore(game_id, was_in_sync)
        GE.bump_data_version()
        changed = True
    else:
        changed = False
    return {"changed": changed, "drift": drift, "live": _scoreboard(game_id)}


@api.delete("/games/{game_id}/events/{event_id}")
def remove_event(game_id: int, event_id: int,
                 _: dict = Depends(require_full_user)):
    ev = query("SELECT id FROM game_events WHERE id=? AND game_id=?",
               (event_id, game_id))
    if not ev:
        raise HTTPException(status_code=404, detail="no such event")
    was_in_sync = _score_in_sync(game_id)
    EL.delete_event(game_id, event_id, EL.game_people(game_id)["pid2team"])
    drift = _post_edit_rescore(game_id, was_in_sync)
    GE.bump_data_version()
    return {"deleted": True, "drift": drift, "live": _scoreboard(game_id)}


@api.post("/games/{game_id}/rescore")
def rescore(game_id: int, _: dict = Depends(require_full_user)):
    """Explicit re-freeze of games.home/away_score from the event stream —
    the PWA's equivalent of the Event Editor page's recompute button. Works
    for tracked AND in-progress games, same as the old page."""
    if not query("SELECT id FROM games WHERE id=?", (game_id,)):
        raise HTTPException(status_code=404, detail="no such game")
    scores = EL.recompute_final_score(game_id)
    if scores is None:
        raise HTTPException(status_code=422, detail="game has no events")
    GE.bump_data_version()
    return {"home": scores[0], "away": scores[1], "live": _scoreboard(game_id)}


# ── PWA shell (service worker + manifest live at root scope) ────────────────────
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/sw.js", include_in_schema=False)
def sw():
    return FileResponse(_STATIC / "sw.js", media_type="application/javascript")


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(_STATIC / "manifest.json", media_type="application/manifest+json")


app.include_router(api)
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
