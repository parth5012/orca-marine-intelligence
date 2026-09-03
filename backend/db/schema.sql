-- ORCA Marine Intelligence — PostGIS Schema
-- Owner: M-B (Data Extractors & Storage)
-- Module: backend/db/schema.sql

-- Enable PostGIS spatial extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- 1. PFZ Zones — Daily potential fishing zone features (INCOIS)
-- ============================================================
CREATE TABLE IF NOT EXISTS pfz_zones (
    id              SERIAL PRIMARY KEY,
    zone_id         VARCHAR(64) UNIQUE NOT NULL,
    place           VARCHAR(256) NOT NULL,          -- e.g. "Pallithottam", "Kochi"
    sector          VARCHAR(32) NOT NULL,           -- e.g. "SEC005"
    sector_name     VARCHAR(64) NOT NULL,           -- e.g. "KERALA"
    direction       VARCHAR(16),                    -- e.g. "SW", "NE"
    bearing         INT,                            -- 0-360 degrees
    depth_range     VARCHAR(32),                    -- e.g. "55-60 m"
    distance_km     FLOAT,                          -- Distance from coast
    lat             FLOAT NOT NULL,
    lon             FLOAT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL, -- WGS84 Point
    intensity       VARCHAR(32) DEFAULT 'medium',   -- low/medium/high
    source          VARCHAR(64) DEFAULT 'incois_textdata',
    valid_date      DATE DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pfz_geom ON pfz_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_pfz_zone_id ON pfz_zones (zone_id);
CREATE INDEX IF NOT EXISTS idx_pfz_sector ON pfz_zones (sector_name);
CREATE INDEX IF NOT EXISTS idx_pfz_valid_date ON pfz_zones (valid_date);

-- ============================================================
-- 2. Coastal Ports — Harbors & Landing Centers Registry
-- ============================================================
CREATE TABLE IF NOT EXISTS coastal_ports (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(128) UNIQUE NOT NULL,   -- e.g. "Kochi"
    state           VARCHAR(64) NOT NULL,           -- e.g. "Kerala"
    aliases         JSONB DEFAULT '{}',             -- Regional spellings
    lat             FLOAT NOT NULL,
    lon             FLOAT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ports_geom ON coastal_ports USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ports_name ON coastal_ports (name);

-- ============================================================
-- 3. EEZ Boundaries — Exclusive Economic Zone Polygons
-- ============================================================
CREATE TABLE IF NOT EXISTS eez_boundaries (
    id              SERIAL PRIMARY KEY,
    country         VARCHAR(64) DEFAULT 'India',
    boundary_name   VARCHAR(128) NOT NULL,          -- e.g. "India EEZ"
    boundary_type   VARCHAR(32) DEFAULT 'EEZ',      -- "EEZ" or "IMBL"
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eez_geom ON eez_boundaries USING GIST (geom);

-- ============================================================
-- 4. MPA Boundaries — Marine Protected Area Polygons
-- ============================================================
CREATE TABLE IF NOT EXISTS mpa_boundaries (
    id              SERIAL PRIMARY KEY,
    mpa_name        VARCHAR(128) NOT NULL,
    state           VARCHAR(64),
    restriction_level VARCHAR(32) DEFAULT 'no-take',
    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mpa_geom ON mpa_boundaries USING GIST (geom);

-- ============================================================
-- 5. Chat Sessions & Messages — Conversation Memory
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id          VARCHAR(64) PRIMARY KEY,
    preferred_language  VARCHAR(8) DEFAULT 'en',
    last_lat            FLOAT,
    last_lon            FLOAT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id                  SERIAL PRIMARY KEY,
    session_id          VARCHAR(64) REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    sender              VARCHAR(16) NOT NULL,       -- "user" or "orca"
    message             TEXT NOT NULL,
    detected_language   VARCHAR(8),
    detected_script     VARCHAR(16),
    advisory_payload    JSONB,                      -- Cards, map coordinates, safety
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id);

-- ============================================================
-- 6. Ingest Log — Track Data Ingestion Runs
-- ============================================================
CREATE TABLE IF NOT EXISTS ingest_runs (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,           -- incois_textdata / copernicus
    status          VARCHAR(32) NOT NULL,           -- success / failed / partial
    feature_count   INT DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);