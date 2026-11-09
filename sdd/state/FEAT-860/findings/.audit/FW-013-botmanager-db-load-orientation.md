---
id: FW-013
query_id: Q004
type: wiki_query
intent: "Find how BotManager loads definitions from the database (BotModel / _load_database_bots)."
executed_at: 2026-11-09T17:13:22Z
duration_ms: 470
parent_id: FW-005
depth: 2
---

# FW-013 — BotManager has a gated DB load path for bots (_load_database_bots) and a separate gated crew load path

## Summary

The query surfaces `BotManager._load_database_bots` (PBAC wiring FEAT-153, factory wiring FEAT-133, hot reload
TASK-2510) and the FEAT-042 initialization flags (`enable_database_bots`, `enable_crews`, `enable_registry_bots`).
`_load_database_bots` is byte-frozen by FEAT-621 AC17 (FW-008), so crew rehydration from Postgres must hook into
the crew path (`load_crews`), not into the bot DB loader.

## Citations

- path: `packages/ai-parrot/tests/manager/test_load_database_bots_pbac.py`
  excerpt: |
    wiki score=31.39 — "Integration tests for BotManager._load_database_bots PBAC wiring — FEAT-153 TASK-1052."
- path: `sdd/tasks/completed/TASK-2510-botmanager-reload-agent.md`
  excerpt: |
    wiki score=24.06 — "BotManager.reload_agent — hot swap of a registered agent"
- path: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
  excerpt: |
    wiki score=20.39 — "BotManager Initialization Flags Decoupling"
- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  lines: 268-283
  symbol: `test_load_database_bots_untouched`
  excerpt: |
    "BotManager._load_database_bots changed since the merge-base"

## Notes

[cross-lane: type=read, intent=read BotManager.load_crews / add_crew / crew_redis init in manager.py (Q008)]
