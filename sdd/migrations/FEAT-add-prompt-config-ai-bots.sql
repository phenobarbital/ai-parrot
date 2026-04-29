-- ============================================================
-- Add prompt_config to navigator.ai_bots
-- ============================================================
-- Table  : navigator.ai_bots
-- Column : prompt_config jsonb
--
-- Purpose:
--   Declarative prompt-layer configuration per bot. Mirrors the
--   YAML PromptConfig contract used by parrot.registry.BotRegistry
--   so DB-loaded bots can pick a preset and apply layer mutations
--   without code changes.
--
-- Shape:
--   {
--     "preset":    "default" | "minimal" | "voice" | "agent" | "rag",
--     "remove":    ["tools", ...],
--     "add":       ["company_context", { "name": "...", "template": "..." }],
--     "customize": { "behavior": { "template": "..." } }
--   }
--
-- Safe   : additive, idempotent, no data loss
-- Status : pending
-- ============================================================

BEGIN;

ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB;

COMMENT ON COLUMN navigator.ai_bots.prompt_config IS
    'Declarative prompt-layer config: {preset, remove[], add[], customize{}}. '
    'See parrot.registry.PromptConfig.';

COMMIT;

-- Rollback:
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS prompt_config;
