---
id: FC-016
query_id: Q016
type: glob
intent: "Existing tests for the self_ CLI and existing migration runners (to mirror test layout)."
executed_at: 2026-11-12T20:42:51Z
duration_ms: 200
parent_id: null
depth: 0
---

# FC-016 — Test layout: tests/self_/ for the CLI, tests/studio/storage/ for migration files + DB

## Summary

Core has a dedicated `packages/ai-parrot/tests/self_/` suite (CLI, doctor, components, uv). The studio runner is covered
by a pure-file test (catalog/checksum/manifest) and a DB test, a split worth mirroring (file-level tests run without
PostgreSQL; DB tests skip when unreachable). A live crew-migration test also exists in server handlers.

## Citations

- path: `packages/ai-parrot/tests/self_/test_self_cli.py`
- path: `packages/ai-parrot/tests/self_/test_doctor.py`
- path: `packages/ai-parrot/tests/self_/test_components.py`
- path: `packages/ai-parrot-server/tests/studio/storage/test_migration_files.py`
- path: `packages/ai-parrot-server/tests/studio/storage/test_migrations_db.py`
- path: `packages/ai-parrot-server/tests/handlers/test_crew_migration_live.py`
- path: `packages/ai-parrot/tests/handlers/test_bot_model_fields.py`

## Notes

`test_bot_model_fields.py` (not read) likely pins BotModel's field set — a candidate anchor for a "catalog covers every
BotModel column" consistency test. Test files were located, not read.
