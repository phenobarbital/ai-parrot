-- ============================================================
-- Fold embedding_model into vector_store_config / vector_config
-- ============================================================
-- Tables  : navigator.ai_bots, navigator.users_bots
-- Columns : (drop) embedding_model jsonb
-- Source  : vector_store_config['embedding_model'] (ai_bots)
--           vector_config['embedding_model']        (users_bots)
--
-- Purpose:
--   Single source of truth for the embedding model used by the
--   bot's vector store. Eliminates the desync between the dedicated
--   embedding_model column and the embedding_model key sometimes
--   nested inside vector_store_config — which caused the wrong
--   model to be loaded at retrieval time.
--
-- Steps (per table):
--   1. Backfill vector_*_config['embedding_model'] from the
--      dedicated column where the JSONB key is missing.
--   2. Normalize the key 'model' -> 'model_name' inside the
--      embedded dict so writers and readers agree.
--   3. Drop the dedicated embedding_model column.
--
-- Safe   : reversible (see Rollback). Backfill is idempotent.
-- Status : pending
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- ai_bots
-- ------------------------------------------------------------

-- 1. Backfill: copy embedding_model column INTO vector_store_config
--    when the JSONB does not already carry it.
UPDATE navigator.ai_bots
SET vector_store_config = jsonb_set(
        COALESCE(vector_store_config, '{}'::jsonb),
        '{embedding_model}',
        embedding_model::jsonb,
        true
    )
WHERE embedding_model IS NOT NULL
  AND (vector_store_config IS NULL
       OR vector_store_config->'embedding_model' IS NULL);

-- 2. Normalize legacy 'model' key -> 'model_name'.
UPDATE navigator.ai_bots
SET vector_store_config = jsonb_set(
        vector_store_config #- '{embedding_model,model}',
        '{embedding_model,model_name}',
        vector_store_config->'embedding_model'->'model',
        true
    )
WHERE vector_store_config->'embedding_model'->>'model' IS NOT NULL
  AND vector_store_config->'embedding_model'->>'model_name' IS NULL;

-- 3. Drop the column.
ALTER TABLE navigator.ai_bots
    DROP COLUMN IF EXISTS embedding_model;

-- ------------------------------------------------------------
-- users_bots
-- ------------------------------------------------------------

-- 1. Backfill: copy embedding_model column INTO vector_config.
UPDATE navigator.users_bots
SET vector_config = jsonb_set(
        COALESCE(vector_config, '{}'::jsonb),
        '{embedding_model}',
        embedding_model::jsonb,
        true
    )
WHERE embedding_model IS NOT NULL
  AND (vector_config IS NULL
       OR vector_config->'embedding_model' IS NULL);

-- 2. Normalize legacy 'model' key -> 'model_name'.
UPDATE navigator.users_bots
SET vector_config = jsonb_set(
        vector_config #- '{embedding_model,model}',
        '{embedding_model,model_name}',
        vector_config->'embedding_model'->'model',
        true
    )
WHERE vector_config->'embedding_model'->>'model' IS NOT NULL
  AND vector_config->'embedding_model'->>'model_name' IS NULL;

-- 3. Drop the column.
ALTER TABLE navigator.users_bots
    DROP COLUMN IF EXISTS embedding_model;

COMMIT;

-- ============================================================
-- Rollback
-- ============================================================
-- BEGIN;
--
-- ALTER TABLE navigator.ai_bots
--     ADD COLUMN IF NOT EXISTS embedding_model JSONB
--     DEFAULT '{"model_name": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}';
-- UPDATE navigator.ai_bots
-- SET embedding_model = vector_store_config->'embedding_model'
-- WHERE vector_store_config->'embedding_model' IS NOT NULL;
--
-- ALTER TABLE navigator.users_bots
--     ADD COLUMN IF NOT EXISTS embedding_model JSONB
--     DEFAULT '{"model_name": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}';
-- UPDATE navigator.users_bots
-- SET embedding_model = vector_config->'embedding_model'
-- WHERE vector_config->'embedding_model' IS NOT NULL;
--
-- COMMIT;
