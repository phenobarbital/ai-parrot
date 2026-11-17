---
id: F020
query_id: Q004
type: wiki_query
intent: "Find any existing Redis→Postgres migration or dual-backend storage pattern to reuse."
executed_at: 2026-11-09T17:13:21Z
duration_ms: 350
parent_id: null
depth: 2
merged_from: [FW-011]
---

# F020 — No existing Redis→Postgres data migration; nearest dual-backend patterns are Studio storage selection and the ResultStorage/Checkpoint factories

## Summary

`wikitoolkit query "migrate redis to postgres storage backend"` returns backend *selection* code, never a
data-moving migration: Studio `storage/backend.py` (auto|database|filesystem matrix, FEAT-621), the ResultStorage
factory (FEAT-147), the CheckpointStore factory (FEAT-399), and the `dynamodb-fallback-redis` brainstorm
(pluggable conversation/artifact backends). None copies existing records from one backend to another, so the
`migration=True` copy loop is new code.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/backend.py`
  excerpt: |
    wiki score=26.30 — "Studio storage backend selection (spec §2.2, §2.7a)."

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/factory.py`
  excerpt: |
    wiki score=23.05 — "Factory for resolving ResultStorage backends by name, instance, or env var."

- path: `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/store/factory.py`
  excerpt: |
    wiki score=22.13 — "Factory for resolving CheckpointStore backends (FEAT-399, TASK-2048)."

- path: `sdd/proposals/dynamodb-fallback-redis.brainstorm.md`
  excerpt: |
    wiki score=20.44 — "Brainstorm: Pluggable Storage Backends for Conversations & Artifacts"

- path: `wiki/bots/agentstudio/db-storage.md`
  excerpt: |
    wiki score=20.71 — "Agent Studio — database storage (host guide)"

## Notes

[cross-lane: type=grep, intent=confirm absence of migrate/migration= copy patterns in code (Q017)]
