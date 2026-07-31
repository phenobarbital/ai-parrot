---
type: Wiki Overview
title: 'TASK-1090: Concept Catalog YAML Seed'
id: doc:sdd-tasks-completed-task-1090-concept-catalog-yaml-seed-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'A CLI/script entry point that seeds concept rows from existing YAML ontology
  files into the Postgres concept catalog. Idempotent: existing rows (any state) are
  skipped. Uses the service''s `propose` + `approve` admin path. See spec §3 Module
  6.'
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog.seed
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1090: Concept Catalog YAML Seed

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1088
**Assigned-to**: unassigned

---

## Context

A CLI/script entry point that seeds concept rows from existing YAML ontology files into the Postgres concept catalog. Idempotent: existing rows (any state) are skipped. Uses the service's `propose` + `approve` admin path. See spec §3 Module 6.

---

## Scope

- Implement `seed_concepts_from_yaml(tenant_id, yaml_path, service)` async function.
- Parse YAML ontology file to extract concept definitions.
- For each concept: call `service.propose_concept(...)` then `service.approve(...)` with `asserted_by="seed:yaml@<file_hash>"`.
- Idempotent: if a concept with the same `(tenant_id, slug)` already exists in any state, skip it.
- Seed is_a edges if the YAML defines hierarchy.
- Write unit tests.

**NOT in scope**: Service logic (TASK-1088), CLI argument parsing (can be a simple async function), HTTP exposure.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/seed.py` | CREATE | seed_concepts_from_yaml function |
| `tests/knowledge/ontology/concept_catalog/test_seed.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService  # TASK-1088
from parrot.knowledge.ontology.schema import OntologyDefinition  # schema.py:155
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/service.py (TASK-1088)
class ConceptCatalogService:
    async def propose_concept(self, tenant_id, slug, label, asserted_by, ...) -> UUID: ...
    async def propose_isa_edge(self, tenant_id, child_id, parent_tier, parent_ref, asserted_by, ...) -> UUID: ...
    async def approve(self, target_id, target_kind, actor, reason=None) -> None: ...
    async def get_live_concepts(self, tenant_id, domain=None) -> list[ConceptRow]: ...
```

### Does NOT Exist

- ~~`seed_concepts_from_yaml`~~ — does not exist; this task creates it.
- ~~An `OntologyParser` class~~ — verify if a YAML parser exists for ontology files. The merger uses `yaml.safe_load` internally. Check `merger.py` for YAML parsing pattern.

---

## Implementation Notes

### Key Constraints

- `asserted_by` must include the file hash for traceability: `"seed:yaml@<sha256[:12]>"`.
- Idempotency: before proposing, check if `(tenant_id, slug)` already exists via `get_live_concepts` or a direct query. Skip if found in any state.
- Process concepts first, then is_a edges (edges reference concept IDs).
- Log each skipped/proposed concept for observability.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` — see how YAML files are parsed.
- Spec §3 Module 6.

---

## Acceptance Criteria

- [ ] `seed_concepts_from_yaml` seeds concepts from YAML with `state='approved'`.
- [ ] Running twice on same tenant produces identical final state (idempotent).
- [ ] Existing rows in any state are skipped.
- [ ] `asserted_by` includes file hash.
- [ ] is_a edges seeded if YAML defines hierarchy.
- [ ] All tests pass: `pytest tests/knowledge/ontology/concept_catalog/test_seed.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/concept_catalog/test_seed.py
import pytest
from parrot.knowledge.ontology.concept_catalog.seed import seed_concepts_from_yaml


class TestSeedIdempotency:
    async def test_seed_twice_same_result(self, concept_service, empty_tenant, sample_yaml):
        await seed_concepts_from_yaml(empty_tenant, sample_yaml, concept_service)
        concepts_after_first = await concept_service.get_live_concepts(empty_tenant)

        await seed_concepts_from_yaml(empty_tenant, sample_yaml, concept_service)
        concepts_after_second = await concept_service.get_live_concepts(empty_tenant)

        assert len(concepts_after_first) == len(concepts_after_second)

    async def test_skips_existing_concepts(self, concept_service, seeded_tenant, sample_yaml):
        count = await seed_concepts_from_yaml(seeded_tenant, sample_yaml, concept_service)
        assert count == 0  # all skipped
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` for YAML parsing pattern
2. **Verify** TASK-1088 service API is available
3. **Implement** idempotent seed function
4. **Run tests**: `pytest tests/knowledge/ontology/concept_catalog/test_seed.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
