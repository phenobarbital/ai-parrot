-- FEAT-574 — idempotent schema change for deployed databases. Safe to run repeatedly.
-- Applied by the operator; the application never runs DDL.
-- A nullable column is NOT a completed migration: migrated planogram types also need a reviewed
-- slots_definition backfill (see the FEAT-574 migration runbook).

ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS slots_definition JSONB NULL;
ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS llm_backend TEXT NULL;
ALTER TABLE troc.planograms_configurations ALTER COLUMN roi_detection_prompt DROP NOT NULL;
ALTER TABLE troc.planograms_configurations ALTER COLUMN object_identification_prompt DROP NOT NULL;
