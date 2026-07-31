---
type: Wiki Overview
title: 'TASK-1098: TenantOntologyManager Extension — PG Overlay Composition'
id: doc:sdd-tasks-completed-task-1098-tenant-ontology-manager-extension-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. Fetch approved concept rows for the tenant → synthesize `OntologyDefinition`
  (`pg_overlay_concepts`).
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
---

# TASK-1098: TenantOntologyManager Extension — PG Overlay Composition

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1086, TASK-1088, TASK-1095
**Assigned-to**: unassigned

---

## Context

`TenantOntologyManager.resolve()` currently resolves from a three-layer YAML chain. This task extends it to compose the YAML chain + PG overlay layer (approved concepts + approved schema overlays) in a single merge via `OntologyMerger.merge_with_overlay()`. The constructor is extended to accept service/reader interfaces for testability. See spec §3 Module 15.

---

## Scope

- Extend `TenantOntologyManager.__init__` to accept optional `concept_catalog_service` and `schema_overlay_service` (or thin reader protocols).
- Extend `resolve()` to:
  1. Fetch approved concept rows for the tenant → synthesize `OntologyDefinition` (`pg_overlay_concepts`).
  2. Fetch approved schema overlays for the tenant → synthesize `OntologyDefinition` (`pg_overlay_schema`).
  3. Call `merger.merge_with_overlay(yaml_paths, [pg_overlay_concepts, pg_overlay_schema])` instead of `merger.merge(yaml_paths)`.
- Backward compatible: if no services provided, `resolve()` behaves exactly as before (YAML-only).
- Write unit tests.

**NOT in scope**: Cache pub/sub subscriber (TASK-1099), HTTP routes, worker logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` | MODIFY | Extend __init__ and resolve() |
| `tests/knowledge/ontology/test_tenant_overlay.py` | CREATE | Unit tests for overlay composition |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.tenant import TenantOntologyManager       # tenant.py:18
from parrot.knowledge.ontology.merger import OntologyMerger               # merger.py:26
from parrot.knowledge.ontology.schema import (
    OntologyDefinition,    # schema.py:155
    MergedOntology,        # schema.py:185
    TenantContext,         # schema.py:261
    EntityDef,             # schema.py:39
    RelationDef,           # schema.py:106
    TraversalPattern,      # schema.py:131
)
from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService  # TASK-1088
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow              # TASK-1087
from parrot.knowledge.ontology.schema_overlay.service import SchemaOverlayService    # TASK-1095
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow         # TASK-1093
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:                                                    # line 18
    def __init__(
        self,
        ontology_dir: Path | str | None = None,
        base_file: str | None = None,
        domains_dir: str | None = None,
        clients_dir: str | None = None,
        db_template: str | None = None,
        pgvector_schema_template: str | None = None,
    ) -> None: ...                                                              # line 37

    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext: ...  # line 74
    def invalidate(self, tenant_id: str | None = None) -> None: ...             # line 165

    # Internal attributes:
    self._cache: dict[str, TenantContext]                                       # line 72
    self._merger: OntologyMerger                                                # line 71
    self._ontology_dir: Path                                                    # line 64

# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py
class OntologyMerger:
    def merge_with_overlay(
        self, yaml_paths: list[Path], overlay_defs: list[OntologyDefinition],
    ) -> MergedOntology: ...                                                    # TASK-1086
```

### Does NOT Exist

- ~~`concept_catalog_service` param on TenantOntologyManager~~ — does not exist; this task adds it.
- ~~`schema_overlay_service` param on TenantOntologyManager~~ — does not exist; this task adds it.
- ~~PG overlay composition in resolve()~~ — does not exist; this task adds it.

---

## Implementation Notes

### Pattern to Follow

```python
class TenantOntologyManager:
    def __init__(
        self,
        ontology_dir: Path | str | None = None,
        base_file: str | None = None,
        domains_dir: str | None = None,
        clients_dir: str | None = None,
        db_template: str | None = None,
        pgvector_schema_template: str | None = None,
        # NEW optional params for PG overlay:
        concept_catalog_service: ConceptCatalogService | None = None,
        schema_overlay_service: SchemaOverlayService | None = None,
    ) -> None:
        ...
        self._concept_service = concept_catalog_service
        self._schema_service = schema_overlay_service

    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext:
        if tenant_id in self._cache:
            return self._cache[tenant_id]

        yaml_paths = self._build_yaml_paths(tenant_id, domain)
        overlay_defs = []

        if self._concept_service:
            concepts = await self._concept_service.get_live_concepts(tenant_id, domain)
            overlay_defs.append(self._build_concept_overlay(concepts))

        if self._schema_service:
            overlays = await self._schema_service.get_approved(tenant_id)
            overlay_defs.append(self._build_schema_overlay(overlays))

        if overlay_defs:
            merged = self._merger.merge_with_overlay(yaml_paths, overlay_defs)
        else:
            merged = self._merger.merge(yaml_paths)

        ctx = TenantContext(...)
        self._cache[tenant_id] = ctx
        return ctx
```

### Key Constraints

- **Backward compatible**: existing callers that don't pass services get YAML-only behavior.
- **resolve() may need to become async** if it calls async service methods. Check current usage — `resolve()` is currently sync. If the codebase calls it synchronously, consider:
  - Making the PG fetch a separate async init step, OR
  - Making `resolve()` async and updating callers.
  - The spec says "composes PG overlay" — verify whether async is required.
- The concept overlay synthesizes an `OntologyDefinition` from approved `ConceptRow` objects.
- The schema overlay synthesizes an `OntologyDefinition` from approved `SchemaOverlayRow` objects, mapping `overlay_kind` to the correct dict field (`entities`, `relations`, `traversal_patterns`).
- **No breaking changes** to existing `TenantOntologyManager.resolve()` public API.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` — current resolve flow.
- Spec §2 "Architectural Design" — merge chain diagram.

---

## Acceptance Criteria

- [ ] `resolve()` includes approved concepts in `MergedOntology` when service is provided.
- [ ] `resolve()` includes approved schema overlays in `MergedOntology` when service is provided.
- [ ] Without services, `resolve()` produces identical output to current behavior.
- [ ] No breaking changes to existing public API.
- [ ] Existing ontology tests still pass.
- [ ] All tests pass: `pytest tests/knowledge/ontology/test_tenant_overlay.py -v`
- [ ] Existing tests pass: `pytest tests/knowledge/ontology/test_tenant*.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/test_tenant_overlay.py
import pytest
from parrot.knowledge.ontology.tenant import TenantOntologyManager


class TestTenantManagerOverlay:
    def test_resolve_without_services_unchanged(self, manager_no_services, tenant_id):
        """Without PG services, resolve behaves identically to pre-FEAT-159."""
        ctx = manager_no_services.resolve(tenant_id)
        assert ctx.ontology is not None

    async def test_resolve_composes_pg_concepts(self, manager_with_services, tenant_with_concepts):
        ctx = manager_with_services.resolve(tenant_with_concepts)
        # verify approved concepts appear in merged ontology

    async def test_resolve_composes_pg_schema_overlays(self, manager_with_services, tenant_with_overlays):
        ctx = manager_with_services.resolve(tenant_with_overlays)
        # verify approved schema overlays appear in merged ontology

    def test_backward_compatible_init(self):
        """Init with no new params works exactly as before."""
        manager = TenantOntologyManager()
        # should not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` carefully — understand the full resolve flow
2. **Check** all callers of `resolve()` to understand sync/async implications
3. **Verify** TASK-1086 (merge_with_overlay), TASK-1088 (concept service), TASK-1095 (schema service) are done
4. **Extend** __init__ and resolve() while maintaining backward compatibility
5. **Run existing tests**: `pytest tests/knowledge/ontology/test_tenant*.py -v`
6. **Run new tests**: `pytest tests/knowledge/ontology/test_tenant_overlay.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
