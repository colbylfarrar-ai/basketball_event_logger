-- ============================================================
--  SCHEMA.SQL
-- ============================================================

CREATE TABLE IF NOT EXISTS teams (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,
    class     TEXT    NOT NULL CHECK(class IN ('B2','B1','A','2A','3A','4A','5A','6A','N/A')),
    gender    TEXT    NOT NULL CHECK(gender IN ('M','F'))
);

CREATE TABLE IF NOT EXISTS players (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id   INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name      TEXT    NOT NULL,
    number    INTEGER NOT NULL,
    height    REAL,
    wingspan  REAL,
    weight    REAL,
    archived  INTEGER NOT NULL DEFAULT 0,
    season    TEXT    NOT NULL DEFAULT 'Current'
);

CREATE TABLE IF NOT EXISTS games (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    team1_id   INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    team2_id   INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    location   TEXT,
    home_score INTEGER,
    away_score INTEGER,
    tracked    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    opponent_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    date        TEXT    NOT NULL,
    home_away   TEXT    NOT NULL CHECK(home_away IN ('Home','Away')),
    location    TEXT,
    team_score  INTEGER,
    opp_score   INTEGER,
    tracked     INTEGER NOT NULL DEFAULT 0,
    season      TEXT    NOT NULL DEFAULT 'Current'
);

CREATE TABLE IF NOT EXISTS officials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    official_id INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS game_lineup_players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id)   ON DELETE CASCADE,
    team_id     INTEGER NOT NULL REFERENCES teams(id)   ON DELETE CASCADE,
    player_id   INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    plus_minus  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game_id, player_id)
);

CREATE TABLE IF NOT EXISTS game_lineup_officials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL REFERENCES games(id)    ON DELETE CASCADE,
    official_id INTEGER NOT NULL REFERENCES officials(id) ON DELETE CASCADE,
    UNIQUE(game_id, official_id)
);

CREATE TABLE IF NOT EXISTS game_event_lineup (
    event_id  INTEGER NOT NULL REFERENCES game_events(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    team_id   INTEGER NOT NULL REFERENCES teams(id),
    PRIMARY KEY (event_id, player_id)
);

CREATE TABLE IF NOT EXISTS game_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    event_type          TEXT    NOT NULL CHECK(event_type IN ('shot','free_throw','foul','turnover')),
    quarter             INTEGER NOT NULL,
    time                TEXT    NOT NULL,
    possession_secs     REAL    NOT NULL DEFAULT 0,
    primary_player_id   INTEGER REFERENCES players(id),
    shot_result         TEXT    CHECK(shot_result IN ('make','miss')),
    rebound_by_id       INTEGER REFERENCES players(id),
    shot_type           INTEGER CHECK(shot_type IN (2,3)),
    pass_from_id        INTEGER REFERENCES players(id),
    shot_created_by_id  INTEGER REFERENCES players(id),
    blocked_by_id       INTEGER REFERENCES players(id),
    guarded_by_id       INTEGER REFERENCES players(id),
    zone                TEXT    CHECK(zone IN ('LC','LW','C','RW','RC')),
    secondary_player_id INTEGER REFERENCES players(id),
    official_id         INTEGER REFERENCES officials(id),
    stolen_by_id        INTEGER REFERENCES players(id),
    play_type           TEXT
);

-- "Assistant scorer" guest links: each row is one standing, revocable token (the
-- link IS the token). Resolves to the owner coach but flagged guest (log-only).
CREATE TABLE IF NOT EXISTS tracker_guest_tokens (
    token       TEXT PRIMARY KEY,
    owner_email TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    revoked     INTEGER NOT NULL DEFAULT 0
);
