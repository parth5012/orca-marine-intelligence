-- ORCA Marine Intelligence — PostGIS Schema
-- Owner: M2 (Data)
-- Module: backend/db/schema.sql

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- PFZ Zones — Daily potential fishing zone features
-- ============================================================
CREATE TABLE IF NOT EXISTS pfz_zones (
    id              SERIAL PRIMARY KEY,
    zone_id         VARCHAR(64) UNIQUE NOT NULL,
    zone_name       VARCHAR(256),
    area_km2        FLOAT,
    intensity       VARCHAR(32),        -- low/medium/high
    source          VARCHAR(64),        -- incois_textdata / copernicus
    geom            GEOMETRY(MultiPolygon, 4326),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pfz_geom ON pfz_zones USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_pfz_zone_id ON pfz_zones (zone_id);

-- ============================================================
-- EEZ Boundaries — Exclusive Economic Zone polygons
-- ============================================================
CREATE TABLE IF NOT EXISTS eez_boundaries (
    id              SERIAL PRIMARY KEY,
    country         VARCHAR(128),
    eez_name        VARCHAR(256),
    geom            GEOMETRY(MultiPolygon, 4326),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eez_geom ON eez_boundaries USING GIST (geom);

-- ============================================================
-- MPA Boundaries — Marine Protected Area polygons
-- ============================================================
CREATE TABLE IF NOT EXISTS mpa_boundaries (
    id              SERIAL PRIMARY KEY,
    mpa_name        VARCHAR(256),
    iucn_category   VARCHAR(32),
    area_km2        FLOAT,
    geom            GEOMETRY(MultiPolygon, 4326),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mpa_geom ON mpa_boundaries USING GIST (geom);

-- ============================================================
-- Ingest Log — Track data ingestion runs
-- ============================================================
CREATE TABLE IF NOT EXISTS ingest_log (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,   -- incois_textdata / copernicus / boundaries
    status          VARCHAR(32) NOT NULL,   -- success / failed / partial
    feature_count   INT,
    error_message   TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);
