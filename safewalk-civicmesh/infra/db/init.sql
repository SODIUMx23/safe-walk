\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE ROLE safewalk LOGIN PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE safewalk TO safewalk;
GRANT USAGE ON SCHEMA public TO safewalk;

CREATE TABLE telemetry (
    received_at TIMESTAMPTZ NOT NULL,
    device_id TEXT NOT NULL,
    payload JSONB NOT NULL
);
SELECT create_hypertable('telemetry', 'received_at', if_not_exists => TRUE);
CREATE INDEX telemetry_device_time ON telemetry(device_id, received_at DESC);
-- Apache-only Timescale build: no proprietary retention/compression policies.
-- Retention is implemented by the application's explicit scheduled DELETEs.

CREATE TABLE hazards (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('HEAD_LEVEL','GROUND_VOID','PATH_OBSTACLE')),
    geom GEOGRAPHY(POINT,4326) NOT NULL,
    simulation BOOLEAN NOT NULL DEFAULT FALSE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX hazards_geography ON hazards USING GIST(geom);
CREATE INDEX hazards_expiry ON hazards(expires_at) WHERE active;
CREATE TABLE hazard_reports (
    hazard_id UUID REFERENCES hazards(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    PRIMARY KEY(hazard_id,device_id)
);
CREATE TABLE tickets (
    id UUID PRIMARY KEY,
    hazard_id UUID UNIQUE REFERENCES hazards(id),
    created_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE incidents (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX incidents_created ON incidents(created_at DESC);
CREATE TABLE voices (
    id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL
);
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO safewalk;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO safewalk;
