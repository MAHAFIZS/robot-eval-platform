-- 001_init.sql

CREATE TABLE IF NOT EXISTS models (
  id            BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  version       TEXT NOT NULL,
  tags          TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  artifact_uri  TEXT,
  commit_hash   TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS suites (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  yaml_spec  TEXT NOT NULL,
  hash       TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS datasets (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  version    TEXT NOT NULL,
  uri        TEXT NOT NULL,
  hash       TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS runs (
  id            BIGSERIAL PRIMARY KEY,
  model_id      BIGINT NOT NULL REFERENCES models(id) ON DELETE RESTRICT,
  suite_id      BIGINT REFERENCES suites(id) ON DELETE SET NULL,
  dataset_id    BIGINT REFERENCES datasets(id) ON DELETE SET NULL,
  backend       TEXT NOT NULL CHECK (backend IN ('mujoco', 'real', 'replay')),
  status        TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed')),
  started_at    TIMESTAMPTZ,
  ended_at      TIMESTAMPTZ,
  summary_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
  report_uri    TEXT,
  error_message TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_model_created_at ON runs(model_id, created_at DESC);

