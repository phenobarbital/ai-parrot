---
type: Wiki Overview
title: 'TASK-1094: Schema Overlay Validator (Dry-Run)'
id: doc:sdd-tasks-completed-task-1094-schema-overlay-validator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The dry-run validator is the mandatory gate between `pending_review` and
  `approved` for schema overlays. It performs a sandboxed merge using `OntologyMerger.merge_with_overlay()`
  against an ephemeral copy of the tenant''s current state, runs `validate_aql` for
  traversal patterns, '
relates_to:
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.validator
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
- concept: mod:parrot.knowledge.ontology.validators
  rel: mentions
---

# TASK-1094: Schema Overlay Validator (Dry-Run)

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1085, TASK-1086, TASK-1093
**Assigned-to**: unassigned

---

## Context

The dry-run validator is the mandatory gate between `pending_review` and `approved` for schema overlays. It performs a sandboxed merge using `OntologyMerger.merge_with_overlay()` against an ephemeral copy of the tenant's current state, runs `validate_aql` for traversal patterns, checks for framework override attempts, and emits a `DryRunReport`. See spec §3 Module 10.

---

## Scope

- Implement `dry_run_overlay(tenant_id, overlay, tenant_manager, merger)` async function.
- Sandboxed merge: create ephemeral overlay list, call `merger.merge_with_overlay()` without mutating the tenant's real cache.
- AQL validation for `traversal_pattern` overlays via existing `validate_aql()`.
- Framework-override check: catch `FrameworkOverrideError` from merger.
- Cycle check for any new relations.
- Return a `DryRunReport` with per-check results and timing.
- Write unit tests.

**NOT in scope**: Service state transitions (TASK-1095), HTTP routes (TASK-1097), actual cache invalidation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/validator.py` | CREATE | dry_run_overlay function |
| `tests/knowledge/ontology/schema_overlay/test_validator.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow, DryRunReport  # TASK-1093
from parrot.knowledge.ontology.merger import OntologyMerger                     # merger.py:26
from parrot.knowledge.ontology.tenant import TenantOntologyManager              # tenant.py:18
from parrot.knowledge.ontology.schema import (
    OntologyDefinition,    # schema.py:155
    EntityDef,             # schema.py:39
    RelationDef,           # schema.py:106
    TraversalPattern,      # schema.py:131
)
from parrot.knowledge.ontology.validators import validate_aql                   # validators.py:36
from parrot.knowledge.ontology.exceptions import (
    FrameworkOverrideError,  # TASK-1085
    DryRunFailedError,       # TASK-1085
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py
class OntologyMerger:
    def merge_with_overlay(
        self, yaml_paths: list[Path], overlay_defs: list[OntologyDefinition],
    ) -> MergedOntology: ...                                                    # TASK-1086

# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:
    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext: ...  # line 74
    # _cache, _merger, _ontology_dir attributes

# packages/ai-parrot/src/parrot/knowledge/ontology/validators.py
async def validate_aql(aql: str, max_depth: int | None = None) -> str: ...      # line 36
```

### Does NOT Exist

- ~~`dry_run_overlay`~~ — does not exist; this task creates it.
- ~~`OntologyMerger.merge_with_overlay()`~~ — created by TASK-1086; verify available.

---

## Implementation Notes

### Pattern to Follow

```python
async def dry_run_overlay(
    tenant_id: str,
    overlay: SchemaOverlayRow,
    tenant_manager: TenantOntologyManager,
    merger: OntologyMerger,
) -> DryRunReport:
    """Sandboxed validation of a schema overlay candidate.

    Performs:
    1. Parse overlay.definition into the appropriate schema type.
    2. Build an OntologyDefinition from the candidate.
    3. Call merger.merge_with_overlay() with current YAML paths + [candidate].
    4. For traversal_pattern: run validate_aql() on the query_template.
    5. Catch FrameworkOverrideError if overlay attempts to mutate framework items.
    6. Return DryRunReport with per-check results.
    """
    ...
```

### Key Constraints

- **Sandboxing**: the dry-run must NOT mutate the tenant's real `_cache`. Use the merger on a separate call, not the cached `resolve()` result.
- **Timeout**: enforce `ONTOLOGY_DRY_RUN_TIMEOUT_S` (default 10s) on the entire dry-run.
- **Check results**: each check in the report should include `check_name`, `passed`, `details`.
- **v1 depth**: YAML parse + `merge_with_overlay` + cycle check + `validate_aql` for traversal patterns + framework-override check. No smoke-test battery.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py` — `validate_aql()` for AQL validation.
- `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` — `merge_with_overlay()` (TASK-1086).

---

## Acceptance Criteria

- [ ] `dry_run_overlay` performs sandboxed merge without mutating real cache.
- [ ] Traversal pattern with invalid AQL → `DryRunReport(ok=False)`.
- [ ] Traversal pattern with valid AQL → `DryRunReport(ok=True)`.
- [ ] Overlay redefining a framework entity → `DryRunReport(ok=False)` with `FrameworkOverrideError` details.
- [ ] Overlay adding a new entity → `DryRunReport(ok=True)`.
- [ ] `tenant_manager.list_tenants()` unchanged after dry_run call (sandbox verified).
- [ ] All tests pass: `pytest tests/knowledge/ontology/schema_overlay/test_validator.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/schema_overlay/test_validator.py
import pytest
from parrot.knowledge.ontology.schema_overlay.validator import dry_run_overlay
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow, DryRunReport


class TestDryRunOverlay:
    async def test_valid_entity_overlay(self, tenant_manager, merger, empty_tenant):
        overlay = SchemaOverlayRow(
            id=..., tenant_id=empty_tenant, overlay_kind="entity_type",
            name="Project", definition={"collection": "projects"},
            state="pending_review", asserted_by="admin",
        )
        report = await dry_run_overlay(empty_tenant, overlay, tenant_manager, merger)
        assert report.ok

    async def test_invalid_aql_traversal(self, tenant_manager, merger, empty_tenant):
        overlay = SchemaOverlayRow(
            id=..., tenant_id=empty_tenant, overlay_kind="traversal_pattern",
            name="bad_query", definition={
                "description": "broken",
                "query_template": "FOR doc IN REMOVE ...",  # mutating AQL
            },
            state="pending_review", asserted_by="admin",
        )
        report = await dry_run_overlay(empty_tenant, overlay, tenant_manager, merger)
        assert not report.ok

    async def test_framework_override_blocked(self, tenant_manager, merger, empty_tenant):
        overlay = SchemaOverlayRow(
            id=..., tenant_id=empty_tenant, overlay_kind="entity_type",
            name="Employee",  # framework entity
            definition={"collection": "employees_v2"},
            state="pending_review", asserted_by="admin",
        )
        report = await dry_run_overlay(empty_tenant, overlay, tenant_manager, merger)
        assert not report.ok

    async def test_sandbox_does_not_mutate_cache(self, tenant_manager, merger, empty_tenant):
        tenants_before = tenant_manager.list_tenants()
        await dry_run_overlay(empty_tenant, ..., tenant_manager, merger)
        assert tenant_manager.list_tenants() == tenants_before
```

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-1085 (exceptions), TASK-1086 (merge_with_overlay), TASK-1093 (models) are done
2. **Read** `validators.py` for `validate_aql` signature
3. **Read** `merger.py` for `merge_with_overlay` usage
4. **Implement** sandboxed validator
5. **Run tests**: `pytest tests/knowledge/ontology/schema_overlay/test_validator.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
