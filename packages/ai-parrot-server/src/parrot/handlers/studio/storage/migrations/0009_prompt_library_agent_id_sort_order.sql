SELECT pg_advisory_xact_lock(4715391001);
ALTER TABLE IF EXISTS navigator.prompt_library ADD COLUMN IF NOT EXISTS agent_id   varchar;
ALTER TABLE IF EXISTS navigator.prompt_library ADD COLUMN IF NOT EXISTS sort_order integer;
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (9, '0009_prompt_library_agent_id_sort_order', '484ca7331a8b7474f53c11e9e0177ab0a09fdbb367812884b770ec30d3f90ee9')
ON CONFLICT (version) DO NOTHING;
