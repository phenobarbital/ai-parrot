# TASK-5454: Ontology pgvector binding + schema advisory lock

**Feature**: FEAT-863 fixgroup-29f95a321dc1
**Spec**: `sdd/specs/fixgroup-29f95a321dc1.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:3a4a89aaf79d`

## Scope

Implement the three fixes in the spec. NOT in scope: other ontology changes.

## Files to Modify

- `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/publisher.py`
- `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/postgres_store.py`
- `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/pg_schema.py`
- `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_pgvector_binding.py` (new)

## Codebase Contract

- `postgres_store._vector_literal(embedding) -> str` exists.
- `pg_schema.ensure_schema(pool, schema, *, embedding_dim, ann_index_kind)` exists.
- `pgvector.asyncpg.register_vector` exists; `pgvector.Vector('[1,2]')` raises.

## Acceptance Criteria

See spec.

## Validation Commands

`PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary -q`

## Completion Note
