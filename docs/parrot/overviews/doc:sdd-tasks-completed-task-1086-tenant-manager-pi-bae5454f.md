---
type: Wiki Overview
title: 'TASK-1086: TenantOntologyManager Pipeline Integration'
id: doc:sdd-tasks-completed-task-1086-tenant-manager-pipeline-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.knowledge.ontology.tenant import TenantOntologyManager # verified:
  tenant.py:18'
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_embedding
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
---

# TASK-1086: TenantOntologyManager Pipeline Integration

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1084, TASK-1085
**Assigned-to**: unassigned

---

## Context

> Module 3 of the spec. Integrates `ConceptEmbeddingPipeline.sync()` into
> `TenantOntologyManager.resolve()` so concept embeddings are refreshed whenever a tenant's
> ontology is resolved. Also adds the `authority/` directory to the YAML loader path so
> per-tenant authority edge files are picked up during resolution.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`:
  - After merge resolves, invoke `ConceptEmbeddingPipeline.sync(tenant_id, concepts)`.
  - **NOTE**: `resolve()` is currently sync (line 74). The pipeline's `sync()` is async. Either make `resolve()` async or use `asyncio.create_task` / fire-and-forget with error logging.
  - Pipeline failures must log at WARNING and NOT block resolve (fail-open).
  - Add `authority/` directory scanning: look for `{ontology_dir}/authority/{tenant_id}.yaml` and append to the YAML chain before merge.
- Add `ConceptEmbeddingPipeline` as an optional `__init__` parameter (default None — backwards compatible).
- Write unit tests for both integration points.

**NOT in scope**: Creating the pipeline itself (TASK-1085), modifying the YAML (TASK-1084), PgVectorStore changes (TASK-1087).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` | MODIFY | Add pipeline hook + authority/ loader path |
| `packages/ai-parrot/tests/knowledge/test_tenant_pipeline_integration.py` | CREATE | Unit tests for integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # verified: tenant.py:18
from parrot.knowledge.ontology.merger import OntologyMerger  # verified: merger.py:26
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext  # verified: schema.py
from parrot.knowledge.ontology.concept_embedding import ConceptEmbeddingPipeline  # TASK-1085 creates this
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:18
class TenantOntologyManager:
    def __init__(
        self,
        ontology_dir: Path | str | None = None,
        base_file: str | None = None,
        domains_dir: str | None = None,
        clients_dir: str | None = None,
        db_template: str | None = None,
        pgvector_schema_template: str | None = None,
    ) -> None:  # line 37

    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext:  # line 74 — SYNC
        # Current flow:
        # 1. Build YAML chain: base → domain → client
        # 2. merger.merge(chain)
        # 3. Build TenantContext
        # 4. Cache and return

    def invalidate(self, tenant_id: str | None = None) -> None:  # line 165
    def list_tenants(self) -> list[str]:  # line 180

# YAML chain construction (inside resolve):
# Line 91-94: base_path = self._ontology_dir / self._base_file
# Line 112-116: domain_path = self._ontology_dir / self._domains_dir / f"{domain}.ontology.yaml"
# Line 126-128: client_path = self._ontology_dir / self._clients_dir / f"{tenant_id}.ontology.yaml"
```

### Does NOT Exist
- ~~`TenantOntologyManager` accepting a `concept_pipeline` init parameter~~ — does NOT exist; this task adds it
- ~~`TenantOntologyManager.resolve()` scanning `authority/` directory~~ — does NOT exist; this task adds it
- ~~`TenantOntologyManager.resolve()` being async~~ — it is SYNC (`def resolve`, line 74). If the pipeline integration needs async, resolve the sync/async boundary here.

---

## Implementation Notes

### Key Decision: sync/async boundary
`resolve()` is currently sync. `ConceptEmbeddingPipeline.sync()` is async. Options:
1. **Make resolve() async** — cleanest but breaks all callers. Check how `resolve()` is called before choosing this path.
2. **Fire-and-forget with asyncio.create_task** — non-blocking, but concepts might not be ready for the first query on that tenant. Spec recommends synchronous embedding with WARN log if > 2s.
3. **Use `asyncio.run_coroutine_threadsafe` or event loop detection** — if an event loop is running, schedule the task; otherwise skip.

Check callers of `resolve()` to determine the right approach. If all callers are already async, option 1 is cleanest.

### Pattern to Follow
```python
# After merge, before caching:
if self._concept_pipeline:
    try:
        concepts = merged.entities.get("Concept", {}).instances  # verify actual attribute
        await self._concept_pipeline.sync(tenant_id, concepts)
    except Exception as exc:
        logger.warning("Concept embedding pipeline failed for tenant '%s': %s", tenant_id, exc)
```

### Key Constraints
- Pipeline failure must NOT block resolve — log WARNING and continue.
- The `authority/` directory path: `self._ontology_dir / "authority" / f"{tenant_id}.yaml"`.
- The authority YAML should be inserted into the chain AFTER the client ontology (last layer before merge).
- Backwards compatible: if no pipeline is provided, resolve behaves exactly as before.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py` — the file to modify
- `packages/ai-parrot/src/parrot/knowledge/ontology/concept_embedding.py` — the pipeline (TASK-1085)

---

## Acceptance Criteria

- [ ] `TenantOntologyManager.__init__` accepts optional `concept_pipeline` parameter
- [ ] `resolve()` invokes `ConceptEmbeddingPipeline.sync()` after merge, before caching
- [ ] Pipeline failure is logged at WARNING and does NOT raise
- [ ] Per-tenant `authority/{tenant_id}.yaml` is added to the YAML chain if the file exists
- [ ] Backwards compatible: no pipeline provided → resolve works as before
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_tenant_pipeline_integration.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_tenant_pipeline_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.ontology.tenant import TenantOntologyManager


class TestTenantPipelineIntegration:
    def test_tenant_manager_invokes_pipeline(self, tmp_path):
        """resolve(tenant_id) calls ConceptEmbeddingPipeline.sync exactly once."""

    def test_tenant_manager_pipeline_failure_is_logged_not_raised(self, tmp_path):
        """Pipeline raises → resolve still returns; failure is logged at WARNING."""

    def test_authority_yaml_loaded(self, tmp_path):
        """Per-tenant authority/<tenant>.yaml is picked up and included in merge chain."""

    def test_no_pipeline_backwards_compatible(self, tmp_path):
        """No pipeline provided → resolve works exactly as before."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1084 and TASK-1085 are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - **Crucially**: check how `resolve()` is called across the codebase to decide sync/async strategy
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1086-tenant-manager-pipeline-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
