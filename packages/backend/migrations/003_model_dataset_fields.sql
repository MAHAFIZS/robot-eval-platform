ALTER TABLE models
ADD COLUMN IF NOT EXISTS uri TEXT;

ALTER TABLE datasets
ADD COLUMN IF NOT EXISTS format TEXT;

UPDATE models
SET uri = COALESCE(uri, 's3://models/' || id || '/model.bin');

UPDATE datasets
SET format = COALESCE(format, 'unknown');
