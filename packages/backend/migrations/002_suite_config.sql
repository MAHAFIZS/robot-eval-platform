ALTER TABLE suites
ADD COLUMN IF NOT EXISTS config_json JSONB;

UPDATE suites
SET config_json = COALESCE(
  config_json,
  '{"episodes_n": 3, "horizon_steps": 50, "seed_start": 0}'::jsonb
);
