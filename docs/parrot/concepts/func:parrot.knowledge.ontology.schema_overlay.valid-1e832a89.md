---
type: Concept
title: dry_run_overlay()
id: func:parrot.knowledge.ontology.schema_overlay.validator.dry_run_overlay
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Sandboxed validation of a schema overlay candidate.
---

# dry_run_overlay

```python
async def dry_run_overlay(tenant_id: str, overlay: SchemaOverlayRow, tenant_manager: TenantOntologyManager, merger: OntologyMerger) -> DryRunReport
```

Sandboxed validation of a schema overlay candidate.

The function does NOT mutate the ``tenant_manager`` cache.  It obtains
the current YAML path chain from the manager's internal state, then
calls ``merger.merge_with_overlay()`` independently.

Args:
    tenant_id: Tenant owning the overlay.
    overlay: The schema overlay row to validate.
    tenant_manager: Provides YAML path resolution for the tenant.
    merger: ``OntologyMerger`` to use for the sandboxed merge.

Returns:
    ``DryRunReport`` with ``ok``, per-check results, and timing.
