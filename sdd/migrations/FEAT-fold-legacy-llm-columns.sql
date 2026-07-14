-- ============================================================
-- Fold legacy LLM-tuning columns into model_config
-- ============================================================
-- Table   : navigator.ai_bots
-- Columns : (drop) model_name  varchar
--                  temperature double precision
--                  max_tokens  integer
--                  top_k       integer
--                  top_p       double precision
-- Source  : model_config (jsonb)
--
-- Purpose:
--   ``model_config`` is the canonical, single source of truth for all
--   LLM tuning (see parrot/handlers/models/bots.py). Older ai_bots
--   tables still carry these values as standalone columns, which drift
--   from the JSONB and break strict row hydration
--   (``BotModel.__init__() got an unexpected keyword argument
--   'model_name'``). This migration backfills any value that lives only
--   in the column into model_config, then drops the columns.
--
-- Steps:
--   1. Backfill each key into model_config where the JSONB key is
--      missing (an explicit model_config value always wins).
--   2. Mirror model_name into the 'model' key (callers read either).
--   3. Drop the dedicated columns.
--
-- Safe   : reversible (see Rollback). Backfill is idempotent and never
--          overwrites an existing model_config key.
-- Status : applied to dev 2026-07-14 (7 ai_bots rows backfilled, columns
--          dropped, no data loss). Pending on staging/prod.
-- ============================================================

BEGIN;

-- 1. Backfill scalar tuning columns into model_config (only when absent).
UPDATE navigator.ai_bots
SET model_config = jsonb_set(
        COALESCE(model_config, '{}'::jsonb),
        '{model_name}', to_jsonb(model_name), true)
WHERE model_name IS NOT NULL
  AND model_config->'model_name' IS NULL;

UPDATE navigator.ai_bots
SET model_config = jsonb_set(
        COALESCE(model_config, '{}'::jsonb),
        '{temperature}', to_jsonb(temperature), true)
WHERE temperature IS NOT NULL
  AND model_config->'temperature' IS NULL;

UPDATE navigator.ai_bots
SET model_config = jsonb_set(
        COALESCE(model_config, '{}'::jsonb),
        '{max_tokens}', to_jsonb(max_tokens), true)
WHERE max_tokens IS NOT NULL
  AND model_config->'max_tokens' IS NULL;

UPDATE navigator.ai_bots
SET model_config = jsonb_set(
        COALESCE(model_config, '{}'::jsonb),
        '{top_k}', to_jsonb(top_k), true)
WHERE top_k IS NOT NULL
  AND model_config->'top_k' IS NULL;

UPDATE navigator.ai_bots
SET model_config = jsonb_set(
        COALESCE(model_config, '{}'::jsonb),
        '{top_p}', to_jsonb(top_p), true)
WHERE top_p IS NOT NULL
  AND model_config->'top_p' IS NULL;

-- 2. Mirror model_name into the 'model' key when only 'model_name' is set.
UPDATE navigator.ai_bots
SET model_config = jsonb_set(
        model_config, '{model}', model_config->'model_name', true)
WHERE model_config->>'model_name' IS NOT NULL
  AND model_config->'model' IS NULL;

-- 3. Drop the legacy columns.
ALTER TABLE navigator.ai_bots
    DROP COLUMN IF EXISTS model_name,
    DROP COLUMN IF EXISTS temperature,
    DROP COLUMN IF EXISTS max_tokens,
    DROP COLUMN IF EXISTS top_k,
    DROP COLUMN IF EXISTS top_p;

COMMIT;

-- ============================================================
-- Rollback
-- ============================================================
-- BEGIN;
--
-- ALTER TABLE navigator.ai_bots
--     ADD COLUMN IF NOT EXISTS model_name  VARCHAR,
--     ADD COLUMN IF NOT EXISTS temperature DOUBLE PRECISION,
--     ADD COLUMN IF NOT EXISTS max_tokens  INTEGER,
--     ADD COLUMN IF NOT EXISTS top_k       INTEGER,
--     ADD COLUMN IF NOT EXISTS top_p       DOUBLE PRECISION;
--
-- UPDATE navigator.ai_bots SET
--     model_name  = model_config->>'model_name',
--     temperature = (model_config->>'temperature')::double precision,
--     max_tokens  = (model_config->>'max_tokens')::integer,
--     top_k       = (model_config->>'top_k')::integer,
--     top_p       = (model_config->>'top_p')::double precision;
--
-- COMMIT;
