---
type: Wiki Overview
title: 'TASK-1095: Schema Overlay Service'
id: doc:sdd-tasks-completed-task-1095-schema-overlay-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `SchemaOverlayService` is the sole SQL writer for the schema overlay
  tables (`ontology_schema_overlay`, `ontology_schema_audit`, `ontology_schema_outbox`).
  It implements the same five-state machine as the concept catalog but with a mandatory
  `dry_run()` gate between `pending_
relates_to:
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.service
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.validator
  rel: mentions
---

# TASK-1095: Schema Overlay Service

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1084, TASK-1085, TASK-1093, TASK-1094
**Assigned-to**: unassigned

---

## Context

The `SchemaOverlayService` is the sole SQL writer for the schema overlay tables (`ontology_schema_overlay`, `ontology_schema_audit`, `ontology_schema_outbox`). It implements the same five-state machine as the concept catalog but with a mandatory `dry_run()` gate between `pending_review` and `approved`. See spec §3 Module 11.

---

## Scope

- Implement `SchemaOverlayService` with all methods from spec §2 "New Public Interfaces".
- Five-state machine with mandatory dry-run gate on approve.
- Transactional discipline: row lock → validate → dry_run → UPDATE → audit INSERT → outbox INSERT.
- If dry-run fails, keep state at `pending_review`, store `dry_run_report` on the row, raise `DryRunFailedError`.
- Write unit tests.

**NOT in scope**: Outbox draining (TASK-1096), HTTP routes (TASK-1097), merger extension (TASK-1086).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/service.py` | CREATE | SchemaOverlayService |
| `tests/knowledge/ontology/schema_overlay/test_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow, DryRunReport  # TASK-1093
from parrot.knowledge.ontology.schema_overlay.validator import dry_run_overlay                # TASK-1094
from parrot.knowledge.ontology.exceptions import DryRunFailedError                            # TASK-1085
```

### Existing Signatures to Use

```python
# TASK-1094 validator:
async def dry_run_overlay(
    tenant_id: str, overlay: SchemaOverlayRow,
    tenant_manager: TenantOntologyManager, merger: OntologyMerger,
) -> DryRunReport: ...
```

### Does NOT Exist

- ~~`SchemaOverlayService`~~ — does not exist; this task creates it.
- ~~`ontology_schema_admin` role~~ — must be added by TASK-1103 in navigator-auth.

---

## Implementation Notes

### Pattern to Follow

```python
class SchemaOverlayService:
    """Operational truth for per-tenant schema overlays."""

    def __init__(self, pg_pool, tenant_manager, merger) -> None:
        self.logger = logging.getLogger("Parrot.Ontology.SchemaOverlay")
        self._pool = pg_pool
        self._tenant_manager = tenant_manager
        self._merger = merger

    async def approve(self, overlay_id: UUID, actor: str, reason: str | None = None) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM ontology_schema_overlay WHERE id = $1 FOR UPDATE", overlay_id,
                )
                # Validate state transition
                overlay = SchemaOverlayRow(**dict(row))

                # Mandatory dry-run gate
                report = await dry_run_overlay(
                    overlay.tenant_id, overlay, self._tenant_manager, self._merger,
                )
                if not report.ok:
                    await conn.execute(
                        "UPDATE ontology_schema_overlay SET dry_run_report = $1 WHERE id = $2",
                        report.model_dump_json(), overlay_id,
                    )
                    raise DryRunFailedError("dry run failed", report=report.model_dump())

                # Proceed with approval
                await conn.execute("UPDATE ontology_schema_overlay SET state = 'approved' ...")
                # INSERT audit + outbox
```

### Key Constraints

- **Dry-run is mandatory**: approve MUST call `dry_run_overlay` before updating state. If it fails, state stays at `pending_review` with `dry_run_report` populated.
- **State machine** is identical to concept catalog: proposed → pending_review → approved → deprecated/rejected.
- **Audit diff**: JSONB `{before: {...}, after: {...}}`.
- **Outbox operations**: `invalidate_cache` (on approve), `deprecate_invalidate` (on deprecate).
- **`ontology_schema_admin` role**: enforced at the HTTP layer (TASK-1097), not in the service.

### References in Codebase

- Spec §2 "SchemaOverlayService" interface.
- Spec §7 "Patterns to Follow" — transactional discipline.

---

## Acceptance Criteria

- [ ] `propose` creates row with state='proposed', writes audit + outbox.
- [ ] `approve` runs `dry_run` first; failure keeps state at `pending_review` with `dry_run_report` populated.
- [ ] `approve` with passing dry-run transitions to `approved`.
- [ ] `DryRunFailedError` raised on dry-run failure.
- [ ] `reject` transitions from proposed/pending_review to rejected.
- [ ] `deprecate` transitions from approved to deprecated.
- [ ] Unique constraint: one live overlay per (tenant, kind, name).
- [ ] `get_pending` returns pending_review + proposed rows for tenant.
- [ ] `get_history` returns audit trail ordered by occurred_at DESC.
- [ ] All tests pass: `pytest tests/knowledge/ontology/schema_overlay/test_service.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/schema_overlay/test_service.py
import pytest
from parrot.knowledge.ontology.schema_overlay.service import SchemaOverlayService
from parrot.knowledge.ontology.exceptions import DryRunFailedError


class TestSchemaOverlayService:
    async def test_propose_creates_proposed_row(self, schema_service, empty_tenant):
        oid = await schema_service.propose(
            tenant_id=empty_tenant, overlay_kind="entity_type",
            name="Project", definition={"collection": "projects"},
            asserted_by="admin",
        )
        assert oid is not None

    async def test_approve_runs_dry_run(self, schema_service, proposed_overlay_id):
        # with valid overlay, approve should succeed
        await schema_service.approve(proposed_overlay_id, "admin")

    async def test_approve_dry_run_failure(self, schema_service, bad_overlay_id):
        with pytest.raises(DryRunFailedError):
            await schema_service.approve(bad_overlay_id, "admin")
        # verify state is still pending_review
        # verify dry_run_report is populated

    async def test_reject_from_proposed(self, schema_service, proposed_overlay_id):
        await schema_service.reject(proposed_overlay_id, "admin", "not needed")

    async def test_deprecate_from_approved(self, schema_service, approved_overlay_id):
        await schema_service.deprecate(approved_overlay_id, "admin")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2 and §3 Module 11
2. **Verify** TASK-1084 (migration), TASK-1085 (exceptions), TASK-1093 (models), TASK-1094 (validator) are done
3. **Implement** service with mandatory dry-run gate on approve
4. **Run tests**: `pytest tests/knowledge/ontology/schema_overlay/test_service.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
