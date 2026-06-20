"""
db.py — SQLite connection factory with season-aware path resolution.

The active season's DB path is read from database/seasons.json on every
connection.  If seasons.json doesn't exist, falls back to analytics.db.
"""
import contextvars
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent   # repo dir: schema.sql + seasons.json
_SCHEMA    = _ROOT / "schema.sql"
_SEASONS   = _ROOT / "seasons.json"


# ── Audit actor ────────────────────────────────────────────────────────────────
# Who is making writes this run/request. Set by the UI layer (auth.require_login →
# every page via page_chrome) and the tracker API (current_api_user) so execute()
# can attribute every write — without db.py importing streamlit (contextvars is
# stdlib + set fresh each run, so a reused thread can't carry a stale actor).
_AUDIT_ACTOR: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "app5_audit_actor", default="")


def set_audit_actor(email) -> None:
    _AUDIT_ACTOR.set((email or "").strip().lower())


# Writes to these tables are config/derived/queue/log — not moderation signal — so
# the audit hook skips them. (game_events INSERTs = normal courtside capture are
# also skipped; its UPDATE/DELETE = edits/tampering ARE logged — see _audit_write.)
_AUDIT_SKIP_TABLES = {
    "app_settings", "change_requests", "audit_log",
    "game_event_lineup", "game_lineup_players", "game_lineup_officials",
}
_AUDIT_RE = re.compile(
    r"^\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+"
    r"[\"'`]?([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def _audit_write(conn, sql, params, lastrowid, rowcount) -> None:
    """Best-effort write-audit on the SAME connection (never via execute() → no
    recursion). Any failure is swallowed so auditing can never break a real write."""
    try:
        m = _AUDIT_RE.match(sql or "")
        if not m:
            return
        verb = m.group(1).split()[0].upper()       # INSERT / UPDATE / DELETE
        table = m.group(2).lower()
        if table in _AUDIT_SKIP_TABLES:
            return
        if table == "game_events" and verb == "INSERT":
            return                                  # skip normal capture; keep edits
        actor = _AUDIT_ACTOR.get("") or "local"
        detail = (sql or "").strip().replace("\n", " ")[:300]
        try:
            pr = repr(tuple(params))[:200]
        except Exception:
            pr = ""
        conn.execute(
            "INSERT INTO audit_log (actor, op, table_name, row_id, rowcount, "
            "detail, params) VALUES (?,?,?,?,?,?,?)",
            (actor, verb, table, lastrowid if verb == "INSERT" else None,
             rowcount, detail, pr))
    except Exception:
        pass


# ── Data directory (lives OUTSIDE any cloud-sync folder) ────────────────────────
# A live SQLite file + its WAL/-shm sidecars must never sit in OneDrive/Dropbox/
# iCloud: a mid-write sync (or opening the app on a second machine) can corrupt
# it. Code + schema stay in the repo; the DATA moves out. Resolution order:
#   1. $APP5_DATA_DIR            (explicit override — put the DB anywhere)
#   2. %LOCALAPPDATA%\APP5       (Windows, per-user, not synced)
#   3. ~/.app5                   (other OS / no LOCALAPPDATA)
def _data_dir() -> Path:
    env = os.environ.get("APP5_DATA_DIR")
    if env:
        d = Path(env)
    else:
        base = os.environ.get("LOCALAPPDATA")
        d = (Path(base) / "APP5") if base else (Path.home() / ".app5")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _migrate_legacy_db(target: Path) -> None:
    """One-time move-out: if `target` is absent but a legacy copy still sits in
    the repo (database/<name>), copy it to the data dir so existing data (teams,
    games, tracked events) survives the relocation. Never overwrites."""
    if target.exists():
        return
    legacy = _ROOT / target.name
    if legacy.exists() and legacy.resolve() != target.resolve():
        try:
            shutil.copy2(legacy, target)
        except OSError:
            pass

# Track which DB files have already been initialised this process
_INIT_DONE: set[str] = set()


# ── Date normalisation ─────────────────────────────────────────────────────────
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Accepted input formats, tried in order. US month/day ordering.
_DATE_FORMATS = (
    "%Y-%m-%d",   # 2026-01-16  (already ISO)
    "%m/%d/%y",   # 1/16/26
    "%m/%d/%Y",   # 1/16/2026
    "%m-%d-%y",   # 1-16-26
    "%m-%d-%Y",   # 1-16-2026
    "%Y/%m/%d",   # 2026/01/16
)


def normalize_date(value) -> str:
    """Parse a date in any accepted format and return ISO 'YYYY-MM-DD'.

    Two-digit years map via strptime's pivot (00-68 -> 2000s). If the value
    can't be parsed it is returned unchanged so a save never loses data.
    """
    if value is None:
        return value
    s = str(value).strip()
    if not s or _ISO_RE.match(s):
        return s
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


# ── Active DB path ─────────────────────────────────────────────────────────────
def get_db_path() -> Path:
    """Return the SQLite path for the active season, under the external data dir.

    The DB file *name* still comes from seasons.json (active season), but it now
    resolves inside `_data_dir()` instead of the repo, and any legacy in-repo copy
    is migrated out on first access."""
    db_file = "analytics.db"
    if _SEASONS.exists():
        import json
        try:
            with open(_SEASONS, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            active = cfg.get("active_season")
            if active:
                season = cfg.get("seasons", {}).get(active, {})
                db_file = season.get("db_file", "analytics.db")
        except Exception:
            pass
    target = _data_dir() / db_file
    _migrate_legacy_db(target)
    return target


# ── Connection factory ────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    # Reliability hardening (matters even single-user on a laptop):
    #   WAL        — readers never block the writer and vice-versa; far fewer
    #                "database is locked" errors when an antivirus / backup / a
    #                second Streamlit tab touches the file mid-write.
    #   busy_timeout — wait up to 5s for a lock instead of erroring instantly.
    #   synchronous=NORMAL — safe under WAL, noticeably faster writes.
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


# ── Database initialisation ───────────────────────────────────────────────────
def initialize_database():
    """Idempotent — safe to call on every page load."""
    db_path = get_db_path()
    key = str(db_path)
    if key in _INIT_DONE:
        return
    _INIT_DONE.add(key)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        if _SCHEMA.exists():
            with open(_SCHEMA, "r", encoding="utf-8") as f:
                conn.executescript(f.read())

        migrations = [
            "ALTER TABLE players        ADD COLUMN archived    INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE players        ADD COLUMN season      TEXT    NOT NULL DEFAULT 'Current'",
            "ALTER TABLE schedule       ADD COLUMN season      TEXT    NOT NULL DEFAULT 'Current'",
            "ALTER TABLE game_lineup_players ADD COLUMN plus_minus INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE teams          ADD COLUMN notes       TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE players        ADD COLUMN position     TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE players        ADD COLUMN availability TEXT    NOT NULL DEFAULT 'Active'",
            # Shooting hand ('right'/'left', default right). Drives dominant- vs
            # weak-hand-side shot splits (helpers/handedness.py: righty -> right
            # floor side = dominant). No CHECK here — a bad ALTER would abort the
            # whole migration loop; the app only ever writes 'right'/'left'.
            "ALTER TABLE players        ADD COLUMN handedness   TEXT    NOT NULL DEFAULT 'right'",
            "ALTER TABLE teams          ADD COLUMN district     TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE games          ADD COLUMN game_type    TEXT    NOT NULL DEFAULT 'Regular'",
            "ALTER TABLE games          ADD COLUMN video_url    TEXT    NOT NULL DEFAULT ''",
            # Exact shot location in court-feet (half-court model in helpers/court.py).
            # Nullable: old shots have only `zone`; new shots store x/y AND a zone
            # derived from it, so every zone-based stat keeps working unchanged.
            "ALTER TABLE game_events     ADD COLUMN shot_x       REAL",
            "ALTER TABLE game_events     ADD COLUMN shot_y       REAL",
            # Idempotency key for the mobile tracker's offline sync: each tap
            # gets a client-generated UUID so a retried upload (flaky gym wifi)
            # can never double-insert. NULL for events logged in the app itself.
            "ALTER TABLE game_events     ADD COLUMN client_uuid  TEXT",
            # Optional one-tap "play call" label on a shot (pnr / iso / post /
            # spot / cut / offscreen / transition / putback / other). Nullable:
            # the tracker tags it only when the coach wants, every existing shot
            # stays NULL, and the inferred play-type view (helpers/playtypes.py)
            # is unaffected. Captures the literal set call that tempo+creation
            # inference can't derive.
            "ALTER TABLE game_events     ADD COLUMN play_type    TEXT",
            # "Assistant scorer" guest links (the link IS the token; log-only,
            # resolves to the owner coach). Separate from app_users.tracker_token
            # so revoking an assistant never touches the coach's own credential.
            "CREATE TABLE IF NOT EXISTS tracker_guest_tokens ("
            " token TEXT PRIMARY KEY, owner_email TEXT NOT NULL,"
            " label TEXT NOT NULL DEFAULT '',"
            " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
            " revoked INTEGER NOT NULL DEFAULT 0)",
            "CREATE INDEX IF NOT EXISTS idx_guest_tokens_owner "
            "ON tracker_guest_tokens(owner_email)",
            # Hygiene: rows retyped away from "shot" before update_event learned
            # to clear the tap location kept stale x/y — scrub them so a later
            # flip back to "shot" can't resurrect a wrong court spot.
            "UPDATE game_events SET shot_x=NULL, shot_y=NULL "
            "WHERE event_type != 'shot' AND shot_x IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS uidx_ge_client_uuid "
            "ON game_events(client_uuid) WHERE client_uuid IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_glp_game_id       ON game_lineup_players(game_id)",
            "CREATE INDEX IF NOT EXISTS idx_glp_game_player   ON game_lineup_players(game_id, player_id)",
            "CREATE INDEX IF NOT EXISTS idx_glp_player_id     ON game_lineup_players(player_id)",
            "CREATE INDEX IF NOT EXISTS idx_ge_game_id         ON game_events(game_id)",
            "CREATE INDEX IF NOT EXISTS idx_gel_event_id       ON game_event_lineup(event_id)",
            "CREATE INDEX IF NOT EXISTS idx_gel_player_id      ON game_event_lineup(player_id)",
            "CREATE INDEX IF NOT EXISTS idx_games_tracked      ON games(tracked)",
            "CREATE INDEX IF NOT EXISTS idx_games_team1        ON games(team1_id)",
            "CREATE INDEX IF NOT EXISTS idx_games_team2        ON games(team2_id)",
            "CREATE INDEX IF NOT EXISTS idx_players_team_arch  ON players(team_id, archived)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uidx_glo ON game_lineup_officials(game_id, official_id)",
            # Soft-delete for refs, mirroring players.archived. game_events.official_id
            # (foul calls) references officials(id) WITHOUT cascade, so a ref who
            # called any logged foul can't be hard-deleted — archive instead.
            "ALTER TABLE officials ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
            "CREATE INDEX IF NOT EXISTS idx_officials_archived ON officials(archived)",
            """CREATE TABLE IF NOT EXISTS app_settings (
                   key   TEXT PRIMARY KEY,
                   value TEXT NOT NULL DEFAULT ''
               )""",
            # Hand-entered player box scores for games NOT play-by-play tracked.
            # Feeds box-derived stats (possessions = FGA + TOV → PPP/ORtg/four
            # factors) without ever setting games.tracked = 1.
            """CREATE TABLE IF NOT EXISTS manual_player_box (
                   id        INTEGER PRIMARY KEY AUTOINCREMENT,
                   game_id   INTEGER NOT NULL REFERENCES games(id)   ON DELETE CASCADE,
                   team_id   INTEGER NOT NULL REFERENCES teams(id)   ON DELETE CASCADE,
                   player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                   min  REAL    NOT NULL DEFAULT 0,
                   fgm  INTEGER NOT NULL DEFAULT 0, fga INTEGER NOT NULL DEFAULT 0,
                   tpm  INTEGER NOT NULL DEFAULT 0, tpa INTEGER NOT NULL DEFAULT 0,
                   ftm  INTEGER NOT NULL DEFAULT 0, fta INTEGER NOT NULL DEFAULT 0,
                   oreb INTEGER NOT NULL DEFAULT 0, dreb INTEGER NOT NULL DEFAULT 0,
                   ast  INTEGER NOT NULL DEFAULT 0, stl INTEGER NOT NULL DEFAULT 0,
                   blk  INTEGER NOT NULL DEFAULT 0, tov INTEGER NOT NULL DEFAULT 0,
                   pf   INTEGER NOT NULL DEFAULT 0,
                   UNIQUE(game_id, player_id)
               )""",
            "CREATE INDEX IF NOT EXISTS idx_mpb_game ON manual_player_box(game_id)",
            "CREATE INDEX IF NOT EXISTS idx_mpb_team ON manual_player_box(team_id)",
            # Login allowlist for st.login (helpers/auth.py). Roles, not auth:
            # Google/OIDC proves who you are; this table says what you may do.
            """CREATE TABLE IF NOT EXISTS app_users (
                   email    TEXT PRIMARY KEY,
                   role     TEXT NOT NULL DEFAULT 'coach'
                            CHECK(role IN ('admin','coach')),
                   name     TEXT NOT NULL DEFAULT '',
                   added_by TEXT NOT NULL DEFAULT '',
                   added_at TEXT NOT NULL DEFAULT (datetime('now'))
               )""",
            # Monetization / tenancy (see scaling-roadmap). Free vs Paid plans,
            # which team a coach belongs to (many coaches -> one team; NULL for
            # admin/owner), and a paid-through date for the future Stripe poll.
            #   plan       'free' | 'paid'  — Paid unlocks tracked depth + tracker
            #   team_id    -> teams(id), the coach's own team (own-data scope)
            #   paid_until ISO date; entitlement honours it when set
            "ALTER TABLE app_users ADD COLUMN team_id    INTEGER",
            "ALTER TABLE app_users ADD COLUMN plan       TEXT NOT NULL DEFAULT 'free'",
            "ALTER TABLE app_users ADD COLUMN paid_until TEXT NOT NULL DEFAULT ''",
            # DEPRECATED, kept readable for the backfills below: teams.in_pool was
            # the FIRST team-level pool flag; app_users.shares_pool was the later
            # per-coach flag. The co-op opt-in is now TEAM-LEVEL again (canonical =
            # teams.shares_pool): a program is one unit — if any coach on a team
            # opts in, the whole team shares + scouts.
            "ALTER TABLE teams ADD COLUMN in_pool INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE app_users ADD COLUMN shares_pool INTEGER NOT NULL DEFAULT 0",
            # Team-level Coaches' Co-op opt-in (AXIS-2 reciprocity, DEFAULT 0 =
            # Solo/private). When 1 the TEAM is "League-wide": every coach on it
            # shares their tracked games into the pool AND scouts every other
            # league-wide team. Solo teams keep full depth on their own games only.
            # A coach's effective league-wide status = their team's flag (admin
            # always; an admin-banned coach is forced Solo regardless).
            "ALTER TABLE teams ADD COLUMN shares_pool INTEGER NOT NULL DEFAULT 0",
            # Admin moderation override: when 1, this coach is BANNED from the
            # Coaches' Co-op regardless of their own shares_pool toggle — their
            # tracked games are purged from the pool and the pool is hidden from
            # them (forced Solo). They keep full depth on their OWN team. Lets the
            # admin cut off a coach polluting the league-wide pool with bad data.
            "ALTER TABLE app_users ADD COLUMN pool_banned INTEGER NOT NULL DEFAULT 0",
            # Denormalized read-path flag: a tracked game is pooled iff its
            # logging coach (games.tracked_by) is League-wide. Recomputed at
            # finish_game, on a toggle flip, and via entitlement.recompute_game_pool.
            "ALTER TABLE games ADD COLUMN in_pool INTEGER NOT NULL DEFAULT 0",
            # Season partition (model A). 'Current' = the ACTIVE season sentinel
            # (matches players/schedule); New Season stamps the outgoing games with
            # the season's real label so stats never blend across seasons. Existing
            # games default 'Current' = the active 2025-2026 season. The friendly
            # display name of the active season lives in app_settings.active_season.
            "ALTER TABLE games ADD COLUMN season TEXT NOT NULL DEFAULT 'Current'",
            "CREATE INDEX IF NOT EXISTS idx_games_season ON games(season)",
            # Name the active season (only if unset — never clobbers a user value).
            "INSERT OR IGNORE INTO app_settings (key, value) "
            "VALUES ('active_season', '2025-2026')",
            # Attribution: email of the coach who logged a tracked game. Drives
            # pool membership (logger's team in_pool flag) and own-vs-others
            # visibility. '' for legacy/app-logged games.
            "ALTER TABLE games ADD COLUMN tracked_by TEXT NOT NULL DEFAULT ''",
            # Per-coach tracker token (replaces the single shared TRACKER_TOKEN):
            # the mobile API resolves Bearer <token> -> this coach, gating the
            # tracker by plan and stamping games.tracked_by. Issued/rotated from
            # the Settings page.
            "ALTER TABLE app_users ADD COLUMN tracker_token TEXT NOT NULL DEFAULT ''",
            # Multi-team staffing: a coach may staff MORE THAN ONE team — the boys
            # AND girls teams of one school. coach_teams is the source of truth for
            # membership; app_users.team_id is kept as the coach's PRIMARY/default
            # team (the first one) for legacy readers + default_team. A dual-staff
            # coach's two teams are coupled for the co-op (one in pool -> both in),
            # enforced in helpers/auth._apply_pool_coupling.
            """CREATE TABLE IF NOT EXISTS coach_teams (
                   coach_email TEXT    NOT NULL,
                   team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                   PRIMARY KEY (coach_email, team_id)
               )""",
            # Scouting: per-team game-plan notes. (The play-drawing board was
            # dropped — streamlit-drawable-canvas is incompatible with Streamlit
            # 1.53 — so scout_plays is removed.) DEPRECATED: notes are now
            # PER-COACH (coach_notes below) so coaches don't see/overwrite each
            # other's notes. scout_notes + teams.notes are kept for the backfill.
            """CREATE TABLE IF NOT EXISTS scout_notes (
                   id      INTEGER PRIMARY KEY AUTOINCREMENT,
                   team_id INTEGER NOT NULL UNIQUE REFERENCES teams(id) ON DELETE CASCADE,
                   notes   TEXT    NOT NULL DEFAULT ''
               )""",
            "DROP TABLE IF EXISTS scout_plays",
            # PER-COACH notes (private to each coach, no cross-coach leak). Two
            # kinds: 'team' (general team notes, was teams.notes) and 'scout'
            # (opponent game-plan, was scout_notes). PK keeps one row per coach,
            # team and kind.
            """CREATE TABLE IF NOT EXISTS coach_notes (
                   coach_email TEXT    NOT NULL,
                   team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                   kind        TEXT    NOT NULL DEFAULT 'scout',
                   notes       TEXT    NOT NULL DEFAULT '',
                   PRIMARY KEY (coach_email, team_id, kind)
               )""",
            # Admin approval queue for destructive ops (write-authz). A non-admin
            # coach's delete becomes a PENDING request (data stays live) that an
            # admin accepts (re-runs the delete) or rejects in Settings → Review.
            # Replay model: store (op, table_name, target_id); apply on accept.
            """CREATE TABLE IF NOT EXISTS change_requests (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   op         TEXT    NOT NULL DEFAULT 'delete',
                   table_name TEXT    NOT NULL,
                   target_id  INTEGER NOT NULL,
                   label      TEXT    NOT NULL DEFAULT '',
                   requester  TEXT    NOT NULL DEFAULT '',
                   status     TEXT    NOT NULL DEFAULT 'pending',
                   created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                   decided_by TEXT    NOT NULL DEFAULT '',
                   decided_at TEXT    NOT NULL DEFAULT ''
               )""",
            "CREATE INDEX IF NOT EXISTS idx_chgreq_status ON change_requests(status)",
            # Write audit trail (moderation): every user-data INSERT/UPDATE/DELETE
            # is logged here by db.execute() with the acting coach, so the admin can
            # see who changed what and act on a rogue coach. Config/derived/queue
            # tables + normal event-capture are filtered out (see _AUDIT_SKIP_TABLES).
            """CREATE TABLE IF NOT EXISTS audit_log (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts         TEXT    NOT NULL DEFAULT (datetime('now')),
                   actor      TEXT    NOT NULL DEFAULT '',
                   op         TEXT    NOT NULL,
                   table_name TEXT    NOT NULL,
                   row_id     INTEGER,
                   rowcount   INTEGER,
                   detail     TEXT    NOT NULL DEFAULT '',
                   params     TEXT    NOT NULL DEFAULT ''
               )""",
            "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)",
            "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor)",
        ]

        for stmt in migrations:
            try:
                conn.execute(stmt)
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # Normalise legacy date text to ISO 'YYYY-MM-DD' so ORDER BY and
        # parsing are reliable. Only touches rows not already ISO.
        for table in ("games", "schedule"):
            try:
                rows = conn.execute(
                    f"SELECT id, date FROM {table} "
                    "WHERE date IS NOT NULL AND date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
                ).fetchall()
                for rid, raw in rows:
                    iso = normalize_date(raw)
                    if iso != raw:
                        conn.execute(
                            f"UPDATE {table} SET date=? WHERE id=?", (iso, rid)
                        )
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # One-time AXIS-2 migration: lift the deprecated team-level pool flag onto
        # the coaches who own those teams (per-coach shares_pool), then derive each
        # game's pooled flag from its logging coach. Guarded by a marker so it can
        # never re-enable a coach who later went Solo.
        try:
            done = conn.execute(
                "SELECT value FROM app_settings WHERE key='mig_shares_pool_v1'"
            ).fetchone()
            if not done:
                conn.execute(
                    "UPDATE app_users SET shares_pool=1 WHERE shares_pool=0 "
                    "AND team_id IN (SELECT id FROM teams WHERE in_pool=1)")
                conn.execute(
                    "UPDATE games SET in_pool=(CASE WHEN tracked_by != '' "
                    "AND tracked_by IN (SELECT email FROM app_users WHERE shares_pool=1) "
                    "THEN 1 ELSE 0 END)")
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) "
                    "VALUES ('mig_shares_pool_v1','1')")
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # One-time TEAM-LEVEL migration: lift the per-coach shares_pool onto the
        # TEAM (a program is one unit — if any of its coaches opted in, the team is
        # League-wide), then re-derive games.in_pool from the logging coach's TEAM
        # flag. Guarded by a marker so a team later set Solo can't be re-enabled.
        try:
            done = conn.execute(
                "SELECT value FROM app_settings WHERE key='mig_team_shares_v1'"
            ).fetchone()
            if not done:
                conn.execute(
                    "UPDATE teams SET shares_pool=1 WHERE id IN "
                    "(SELECT team_id FROM app_users "
                    " WHERE shares_pool=1 AND team_id IS NOT NULL)")
                conn.execute(
                    "UPDATE games SET in_pool=(CASE WHEN tracked_by != '' "
                    "AND tracked_by IN (SELECT u.email FROM app_users u "
                    " JOIN teams t ON u.team_id=t.id "
                    " WHERE t.shares_pool=1 AND u.pool_banned=0) "
                    "THEN 1 ELSE 0 END)")
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) "
                    "VALUES ('mig_team_shares_v1','1')")
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # One-time: seed coach_teams (multi-team membership) from the single
        # app_users.team_id each coach had, so existing coaches keep their team.
        # Idempotent (INSERT OR IGNORE) + guarded so it never fights later edits.
        try:
            done = conn.execute(
                "SELECT value FROM app_settings WHERE key='mig_coach_teams_v1'"
            ).fetchone()
            if not done:
                conn.execute(
                    "INSERT OR IGNORE INTO coach_teams (coach_email, team_id) "
                    "SELECT email, team_id FROM app_users WHERE team_id IS NOT NULL")
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) "
                    "VALUES ('mig_coach_teams_v1','1')")
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # One-time: migrate the OLD global notes (teams.notes + scout_notes) into
        # the per-coach coach_notes table, assigned to the founding admin (the only
        # person who could have written them in single-admin use). Guarded marker.
        try:
            done = conn.execute(
                "SELECT value FROM app_settings WHERE key='mig_coach_notes_v1'"
            ).fetchone()
            if not done:
                admin = conn.execute(
                    "SELECT email FROM app_users WHERE role='admin' "
                    "ORDER BY added_at LIMIT 1").fetchone()
                if admin:
                    ae = admin[0]
                    conn.execute(
                        "INSERT OR IGNORE INTO coach_notes "
                        "(coach_email, team_id, kind, notes) "
                        "SELECT ?, id, 'team', notes FROM teams "
                        "WHERE notes IS NOT NULL AND notes != ''", (ae,))
                    conn.execute(
                        "INSERT OR IGNORE INTO coach_notes "
                        "(coach_email, team_id, kind, notes) "
                        "SELECT ?, team_id, 'scout', notes FROM scout_notes "
                        "WHERE notes IS NOT NULL AND notes != ''", (ae,))
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) "
                    "VALUES ('mig_coach_notes_v1','1')")
                conn.commit()
        except sqlite3.OperationalError:
            pass

        conn.commit()
    finally:
        conn.close()


# ── SELECT ─────────────────────────────────────────────────────────────────────
def query(sql: str, params: tuple = ()) -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


# ── INSERT / UPDATE / DELETE ───────────────────────────────────────────────────
def execute(sql: str, params: tuple = ()):
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        _lr, _rc = cur.lastrowid, cur.rowcount
        _audit_write(conn, sql, params, _lr, _rc)   # attribute the write to the actor
        conn.commit()
        return _lr
    finally:
        conn.close()


# ── Batch INSERT / UPDATE / DELETE ─────────────────────────────────────────────
def executemany(sql: str, seq_of_params: list) -> int:
    conn = get_connection()
    try:
        cur = conn.executemany(sql, seq_of_params)
        conn.commit()
        _rc = cur.rowcount
        _audit_write(conn, sql, (), None, _rc)
        conn.commit()
        return _rc
    finally:
        conn.close()


# ── Player removal (delete-or-archive) ─────────────────────────────────────────
# game_events points at players(id) through these 8 columns, and NONE of them
# carry ON DELETE CASCADE (only game_lineup_players does). So a player who appears
# in any tracked event can't be hard-deleted — DELETE FROM players raises
# "FOREIGN KEY constraint failed". Such players are archived instead, which keeps
# the box scores that reference them intact and hides them from every roster
# (all roster reads filter archived=0).
_PLAYER_EVENT_COLS = (
    "primary_player_id", "rebound_by_id", "pass_from_id", "shot_created_by_id",
    "blocked_by_id", "guarded_by_id", "secondary_player_id", "stolen_by_id",
)


def player_has_history(pid) -> bool:
    """True if a player has ANY game footprint a hard-delete would lose. Covers
    every table that references players(id):
      - game_events (8 cols) + game_event_lineup — FK without cascade (delete would
        FK-fail), and they hold the player's tracked play-by-play.
      - manual_player_box — ON DELETE CASCADE, so a plain delete would silently wipe
        a hand-entered box score.
      - game_lineup_players — ON DELETE CASCADE; holds per-game roster + plus_minus.
    The two cascade tables are the silent-data-loss risks; the rest FK-fail loudly.
    Any hit → caller archives (archived=1) instead of hard-deleting."""
    pid = int(pid)
    where = " OR ".join(f"{c}=?" for c in _PLAYER_EVENT_COLS)
    if query(f"SELECT 1 FROM game_events WHERE {where} LIMIT 1",
             (pid,) * len(_PLAYER_EVENT_COLS)):
        return True
    for tbl in ("game_event_lineup", "manual_player_box", "game_lineup_players"):
        if query(f"SELECT 1 FROM {tbl} WHERE player_id=? LIMIT 1", (pid,)):
            return True
    return False


def delete_or_archive_player(pid) -> str:
    """Remove a player from active rosters. Hard-deletes when they have no tracked
    history; otherwise archives (archived=1) so the game_events / box scores that
    reference them survive. Returns 'deleted' or 'archived'."""
    pid = int(pid)
    if player_has_history(pid):
        execute("UPDATE players SET archived=1 WHERE id=?", (pid,))
        return "archived"
    execute("DELETE FROM players WHERE id=?", (pid,))
    return "deleted"


def official_has_history(oid) -> bool:
    """True if a ref is referenced by any logged foul (game_events.official_id) or
    has worked a game (game_lineup_officials) — i.e. hard-deleting them would
    violate an FK or drop a games-worked record."""
    oid = int(oid)
    if query("SELECT 1 FROM game_events WHERE official_id=? LIMIT 1", (oid,)):
        return True
    return bool(query("SELECT 1 FROM game_lineup_officials WHERE official_id=? LIMIT 1",
                      (oid,)))


def delete_or_archive_official(oid) -> str:
    """Remove a ref from active selection lists. Hard-deletes when they have no
    history; otherwise archives (archived=1) so the foul calls / games-worked rows
    that reference them survive. Returns 'deleted' or 'archived'."""
    oid = int(oid)
    if official_has_history(oid):
        execute("UPDATE officials SET archived=1 WHERE id=?", (oid,))
        return "archived"
    execute("DELETE FROM officials WHERE id=?", (oid,))
    return "deleted"


# ── Auto-init ──────────────────────────────────────────────────────────────────
initialize_database()
