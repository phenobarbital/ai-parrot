---
type: Wiki Overview
title: 'TASK-1084: Postgres Migration — Ontology Curation Tables'
id: doc:sdd-tasks-completed-task-1084-postgres-migration-ontology-curation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the first task in the FEAT-159 feature. All seven new Postgres tables
  (4 concept-side, 3 schema-side) plus their indexes and constraints must land before
  any service code can be written. See spec §2 Data Models and §3 Module 1.
---

# TASK-1084: Postgres Migration — Ontology Curation Tables

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the first task in the FEAT-159 feature. All seven new Postgres tables (4 concept-side, 3 schema-side) plus their indexes and constraints must land before any service code can be written. See spec §2 Data Models and §3 Module 1.

---

## Scope

- Create the SQL migration file with all 7 tables, unique/partial indexes, CHECK constraints, and GIN index.
- Create a matching rollback script.
- Tables: `ontology_concept`, `ontology_concept_isa`, `ontology_concept_audit`, `ontology_concept_outbox`, `ontology_schema_overlay`, `ontology_schema_audit`, `ontology_schema_outbox`.
- All indexes defined in the spec's §2 Postgres schema section.

**NOT in scope**: Pydantic models, service logic, HTTP routes, Arango collections.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/migrations/<timestamp>_ontology_curation.sql` | CREATE | Forward migration: 7 tables + indexes |
| `packages/ai-parrot/migrations/<timestamp>_ontology_curation_rollback.sql` | CREATE | Rollback: DROP tables in reverse order |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# No Python imports needed — this is a SQL-only task.
```

### Existing Signatures to Use

```sql
-- Verify migration directory pattern before creating files.
-- Known: packages/ai-parrot/migrations/ is the migration directory.
-- Use the project's existing migration naming convention (check existing files).
```

### Does NOT Exist

- ~~`ontology_concept` table~~ — does not exist; this task creates it.
- ~~`ontology_concept_isa` table~~ — does not exist; this task creates it.
- ~~`ontology_concept_audit` table~~ — does not exist; this task creates it.
- ~~`ontology_concept_outbox` table~~ — does not exist; this task creates it.
- ~~`ontology_schema_overlay` table~~ — does not exist; this task creates it.
- ~~`ontology_schema_audit` table~~ — does not exist; this task creates it.
- ~~`ontology_schema_outbox` table~~ — does not exist; this task creates it.
- ~~`tenant_ontology_version` column~~ — not part of this migration (deferred per open question §8).

---

## Implementation Notes

### Pattern to Follow

Check existing migration files in `packages/ai-parrot/migrations/` for naming convention and style. Use the exact DDL from spec §2 Postgres schema section.

### Key Constraints

- UUID primary keys with `gen_random_uuid()`.
- State columns use CHECK constraints with the 5-state enum: `('proposed','pending_review','approved','rejected','deprecated')`.
- Partial unique indexes enforce "only one live concept per (tenant, slug)" — see `uq_ontology_concept_live`.
- GIN index on `(tenant_id, synonyms)` for synonym collision detection (concept table only).
- `ontology_concept_isa.parent_ref` is VARCHAR, not UUID — it holds either a framework concept name (string) or a tenant UUID as text.
- `ontology_concept_outbox.id` and `ontology_schema_outbox.id` use `BIGSERIAL`, not UUID.
- Rollback must DROP tables in reverse dependency order (outbox/audit first, then main tables).

### References in Codebase

- Spec §2 "Postgres schema" — full DDL is provided verbatim; copy it.
- Check `packages/ai-parrot/migrations/` for existing migration naming convention.

---

## Acceptance Criteria

- [ ] Migration file exists with all 7 tables.
- [ ] All CHECK constraints match the 5-state enum.
- [ ] All partial indexes present (uq_ontology_concept_live, uq_ontology_schema_overlay_live, review queue indexes, approved lookup indexes).
- [ ] GIN index on `ontology_concept.synonyms` present.
- [ ] Rollback script drops all tables cleanly.
- [ ] Migration applies cleanly against a fresh database.
- [ ] Rollback runs cleanly after forward migration.

---

## Test Specification

```sql
-- Manual verification (no pytest — pure SQL task):
-- 1. Apply migration:
--    psql -f packages/ai-parrot/migrations/<timestamp>_ontology_curation.sql
-- 2. Verify tables exist:
--    \dt ontology_*
-- 3. Verify indexes:
--    \di ontology_*
-- 4. Rollback:
--    psql -f packages/ai-parrot/migrations/<timestamp>_ontology_curation_rollback.sql
-- 5. Verify tables are gone:
--    \dt ontology_*  (should be empty)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/topic-authority-ontology.spec.md` §2 Data Models for full DDL
2. **Check existing migrations** in `packages/ai-parrot/migrations/` for naming convention
3. **Copy the DDL verbatim** from the spec — do not modify column types or constraints
4. **Write the rollback** in reverse dependency order
5. **Verify** migration applies and rolls back cleanly

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
