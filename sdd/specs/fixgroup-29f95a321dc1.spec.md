---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [ontology, pgvector, postgres, bugfix]
---

# Feature Specification: Ontology pgvector binding + schema lock

**Feature ID**: FEAT-863
**Date**: 2026-11-10
**Author**: Jesus Lara
**Status**: approved
**Discovered-from**: `issue:3a4a89aaf79d` (FEAT-824 code review)

## Problem

1. `PostgresOntologyPublisher._write_version` binds `embedding` as a Python list into a
   `vector` column. That only encodes when the pool has the pgvector codec registered
   (`create_ontology_pg_pool`); a caller-owned pool fails as soon as an `embed` function is set.
2. `PostgresOntologyStore.search` binds `_vector_literal(...)` (text) as `$3::vector`; on a pool
   that DOES have the codec, asyncpg routes the str to `Vector(...)`, which raises.
3. `pg_schema.ensure_schema` runs the DDL without an advisory lock, so concurrent first-time
   callers race on `CREATE ... IF NOT EXISTS`.

## Solution

- Bind every embedding as the pgvector text form with `$n::text::vector`: the parameter type is
  `text`, so it works with and without the codec.
- Take `pg_advisory_xact_lock(hashtext('parrot-ontology-schema:' || schema))` as the first
  statement of the DDL transaction.

## Acceptance Criteria

- Publishing with an `embed` function succeeds on a codec-less pool and on a codec pool.
- Vector search works on both pool kinds.
- Concurrent `ensure_schema` calls on a fresh schema all succeed.
