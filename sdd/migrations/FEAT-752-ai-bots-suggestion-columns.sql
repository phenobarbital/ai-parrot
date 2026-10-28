-- FEAT-752 (TASK-4811): follow-up suggestion chip settings on navigator.ai_bots (Agent Studio).
--
-- Apply BEFORE deploying the code: BotModel selects these columns and fails on a missing one.
-- Idempotent: safe to re-run on any environment. Defaults match AbstractBot's constructor defaults.

BEGIN;

ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS enable_suggestions   BOOLEAN DEFAULT FALSE;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS suggest_followups    BOOLEAN DEFAULT FALSE;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS suggestion_timeout_s REAL    DEFAULT 4.0;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS max_suggestions      INTEGER DEFAULT 6;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS suggestion_model     VARCHAR;

COMMENT ON COLUMN navigator.ai_bots.enable_suggestions   IS 'FEAT-752 — offer deterministic follow-up chips';
COMMENT ON COLUMN navigator.ai_bots.suggest_followups    IS 'FEAT-752 — also ask the lightweight LLM for follow-up questions';
COMMENT ON COLUMN navigator.ai_bots.suggestion_timeout_s IS 'FEAT-752 — timeout in seconds for the LLM chip call';
COMMENT ON COLUMN navigator.ai_bots.max_suggestions      IS 'FEAT-752 — maximum number of chips per answer';
COMMENT ON COLUMN navigator.ai_bots.suggestion_model     IS 'FEAT-752 — optional model for the chip call (default: lightweight model)';

COMMIT;

-- Rollback:
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS suggestion_model;
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS max_suggestions;
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS suggestion_timeout_s;
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS suggest_followups;
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS enable_suggestions;
