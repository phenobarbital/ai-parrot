-- FEAT-593 (TASK-3652): Agent Studio tooling columns on navigator.ai_bots.
--
-- Homologates environments where only part of the FEAT-593 DDL landed
-- (production on 2026-09-29 had `toolkit_config` but not `mcp_servers`,
-- so every BotModel GET failed with: column "mcp_servers" does not exist).
--
-- Idempotent: safe to re-run on any environment.

BEGIN;

ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS toolkit_config JSONB DEFAULT '{}'::JSONB;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS mcp_servers    JSONB DEFAULT '[]'::JSONB;

COMMENT ON COLUMN navigator.ai_bots.toolkit_config IS 'FEAT-593 — per-toolkit config {slug: ToolkitSpec}; secrets in vault';
COMMENT ON COLUMN navigator.ai_bots.mcp_servers    IS 'FEAT-593 — agent-level MCP servers; auth/headers/env in vault';

COMMIT;

-- Rollback:
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS mcp_servers;
