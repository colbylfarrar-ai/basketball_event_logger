-- ============================================================
--  SUPABASE SCHEMA — Run this in Supabase SQL Editor when
--  creating a new season's Supabase project.
--  PostgreSQL compatible.
-- ============================================================

CREATE TABLE IF NOT EXISTS teams (
    id      BIGSERIAL PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    class   TEXT NOT NULL CHECK(class IN ('B2','B1','A','2A','3A','4A','5A','6A','N/A')),
    gender  TEXT NOT NULL CHECK(gender IN ('M','F')),
    notes   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS players (
    id       BIGSERIAL PRIMARY KEY,
    team_id  BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    name     TEXT   NOT NULL,
    number   INTEGER NOT NULL,
    height   REAL,
    wingspan REAL,
    weight   REAL,
    archived INTEGER NOT NULL DEFAULT 0,
    season   TEXT    NOT NULL DEFAULT 'Current'
);

CREATE TABLE IF NOT EXISTS officials (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT    NOT NULL,
    official_id INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS games (
    id         BIGSERIAL PRIMARY KEY,
    team1_id   BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    team2_id   BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    date       TEXT   NOT NULL,
    location   TEXT,
    home_score INTEGER,
    away_score INTEGER,
    tracked    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS schedule (
    id          BIGSERIAL PRIMARY KEY,
    team_id     BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    opponent_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    date        TEXT   NOT NULL,
    home_away   TEXT   NOT NULL CHECK(home_away IN ('Home','Away')),
    location    TEXT,
    team_score  INTEGER,
    opp_score   INTEGER,
    tracked     INTEGER NOT NULL DEFAULT 0,
    season      TEXT    NOT NULL DEFAULT 'Current'
);

CREATE TABLE IF NOT EXISTS game_lineup_players (
    id        BIGSERIAL PRIMARY KEY,
    game_id   BIGINT NOT NULL REFERENCES games(id)   ON DELETE CASCADE,
    team_id   BIGINT NOT NULL REFERENCES teams(id)   ON DELETE CASCADE,
    player_id BIGINT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    plus_minus INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game_id, player_id)
);

CREATE TABLE IF NOT EXISTS game_lineup_officials (
    id          BIGSERIAL PRIMARY KEY,
    game_id     BIGINT NOT NULL REFERENCES games(id)     ON DELETE CASCADE,
    official_id BIGINT NOT NULL REFERENCES officials(id) ON DELETE CASCADE,
    UNIQUE(game_id, official_id)
);

CREATE TABLE IF NOT EXISTS game_events (
    id                  BIGSERIAL PRIMARY KEY,
    game_id             BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    event_type          TEXT   NOT NULL CHECK(event_type IN ('shot','free_throw','foul','turnover')),
    quarter             INTEGER NOT NULL,
    time                TEXT    NOT NULL,
    possession_secs     REAL    NOT NULL DEFAULT 0,
    primary_player_id   BIGINT REFERENCES players(id),
    shot_result         TEXT   CHECK(shot_result IN ('make','miss')),
    rebound_by_id       BIGINT REFERENCES players(id),
    shot_type           INTEGER CHECK(shot_type IN (2,3)),
    pass_from_id        BIGINT REFERENCES players(id),
    shot_created_by_id  BIGINT REFERENCES players(id),
    blocked_by_id       BIGINT REFERENCES players(id),
    guarded_by_id       BIGINT REFERENCES players(id),
    zone                TEXT   CHECK(zone IN ('LC','LW','C','RW','RC')),
    secondary_player_id BIGINT REFERENCES players(id),
    official_id         BIGINT REFERENCES officials(id),
    stolen_by_id        BIGINT REFERENCES players(id)
);

CREATE TABLE IF NOT EXISTS game_event_lineup (
    event_id  BIGINT NOT NULL REFERENCES game_events(id) ON DELETE CASCADE,
    player_id BIGINT NOT NULL REFERENCES players(id),
    team_id   BIGINT NOT NULL REFERENCES teams(id),
    PRIMARY KEY (event_id, player_id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

-- ── Indexes ────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_glp_game_id     ON game_lineup_players(game_id);
CREATE INDEX IF NOT EXISTS idx_glp_game_player ON game_lineup_players(game_id, player_id);
CREATE INDEX IF NOT EXISTS idx_glp_player_id   ON game_lineup_players(player_id);
CREATE INDEX IF NOT EXISTS idx_ge_game_id       ON game_events(game_id);
CREATE INDEX IF NOT EXISTS idx_gel_event_id     ON game_event_lineup(event_id);
CREATE INDEX IF NOT EXISTS idx_gel_player_id    ON game_event_lineup(player_id);
CREATE INDEX IF NOT EXISTS idx_games_tracked    ON games(tracked);
CREATE INDEX IF NOT EXISTS idx_games_team1      ON games(team1_id);
CREATE INDEX IF NOT EXISTS idx_games_team2      ON games(team2_id);
CREATE INDEX IF NOT EXISTS idx_players_team_arch ON players(team_id, archived);
