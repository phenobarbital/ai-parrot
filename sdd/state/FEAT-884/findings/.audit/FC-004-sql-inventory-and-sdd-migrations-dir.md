---
id: FC-004
query_id: Q008
type: glob
intent: "List SQL DDL files shipped in the repo (schema definitions to fold into migrations)."
executed_at: 2026-11-12T20:40:51Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-004 — SQL inventory: four unrelated migration conventions, plus an unmanaged sdd/migrations/ folder

## Summary

`packages/**/*.sql` (excluding build/) holds ~30 files following at least four different conventions: (1) Agent Studio's
ledger-tracked `studio/storage/migrations/000N_*.sql` (0001-0009, see FC-011); (2) parrot-formdesigner's numbered
`migrations/00N_*.sql` (gaps: 001,002,004,005,008,009); (3) task_memory's `migrations/001_task_memory.sql`;
(4) one-off `*_creation.sql` / `table.sql` / `schema.sql` setup files. Follow-up (depth 1): the repo-root
`sdd/migrations/` folder holds 17 hand-run SQL scripts with free-form names, NOT packaged and NOT ledger-tracked,
mixing ai_bots schema changes with unrelated data/config migrations (planogram, ontology, NAV-7762).

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/`
  excerpt: |
    0001_studio_migrations_ledger.sql 0002_ai_agents.sql 0003_ai_agent_drafts.sql 0004_ai_skills_catalog_tenancy.sql
    0005_studio_drafts_baseline.sql 0006_ai_user_llm_keys.sql 0007_ai_user_credentials.sql
    0008_ai_user_toolkit_overrides.sql 0009_prompt_library_agent_id_sort_order.sql

- path: `packages/parrot-formdesigner/migrations/`
  excerpt: |
    001_add_form_uid.sql 002_add_form_uid_submissions.sql 004_form_uid_uuid_type.sql
    005_question_bank_question_id.sql 008_snippet_store.sql 009_voice_envelope_form_data.sql

- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql`

- path: `packages/ai-parrot-server/src/parrot/handlers/models/`
  excerpt: |
    users_bots_creation.sql users_prompts_creation.sql notification_batches_creation.sql notification_templates_creation.sql

- path: `packages/ai-parrot/src/parrot/security/security_events.sql`, `packages/ai-parrot/src/parrot/storage/security_reports/schema.sql`, `packages/ai-parrot/src/parrot/pipelines/table.sql`, `packages/ai-parrot-pipelines/src/parrot_pipelines/table.sql`, `packages/ai-parrot-pipelines/src/parrot_pipelines/alter_planograms_configurations_feat574.sql`, `packages/ai-parrot-squawk/src/parrot/squawk/sql/squawk_served_ledger.sql`, `packages/ai-parrot-semantic/src/parrot/semantic/sql/semantic_audit_events.sql`

- path: `sdd/migrations/`
  excerpt: |
    ai-bots-homologate-botmodel.sql  botmodel-recreate-table.sql  FEAT-593-ai-bots-tooling-columns.sql
    FEAT-638-bot-language-nullable.sql  FEAT-752-ai-bots-suggestion-columns.sql  FEAT-add-prompt-config-ai-bots.sql
    FEAT-fix-stale-bot-tool-names.sql  FEAT-fold-embedding-model-into-vector-store-config.sql
    FEAT-fold-legacy-llm-columns.sql  (ai_bots-related: 9)
    FEAT-096-planogram15-config{,-v2,-v3}.sql  FEAT-159-ontology-curation{,-rollback}.sql  NAV-7762-ecotank-endcap-rows.sql

## Notes

sdd/migrations/ is outside every distribution, so an installed `ai-parrot` cannot run it — the would-be catalog must
live inside a package (importlib.resources, as studio does). The ai_bots scripts have no order key; the ordering
must be reconstructed (git history: [cross-lane: type=git_log, intent=commit dates of sdd/migrations/*ai-bots* files to derive an order]).
